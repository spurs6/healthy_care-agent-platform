"""
OpenEvidence 临床证据助手 - PDF文档解析模块
使用pymupdf4llm进行PDF到Markdown的转换
"""
import os
import re
import json
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from bisect import bisect_right

import pymupdf4llm
import pymupdf

from backend.config import CHUNK_WINDOW, CHUNK_OVERLAP, MIN_CHUNK_TOKEN
from backend.db_store import ChunkMeta, article_dao


class PDFParser:
    """PDF文档解析器"""
    
    def __init__(self):
        self.supported_extensions = ['.pdf']
    
    def parse_pdf_to_markdown(self, pdf_path: str) -> Dict[str, Any]:
        """
        将PDF转换为结构化Markdown

        Args:
            pdf_path: PDF文件路径

        Returns:
            解析结果，包含markdown文本、页码映射等
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

        try:
            # 使用pymupdf4llm转换
            md_text = pymupdf4llm.to_markdown(pdf_path)

            # 获取页码信息和字符→页码映射
            doc = pymupdf.open(pdf_path)
            page_count = doc.page_count
            page_text_mapping = self._build_page_mapping(doc, md_text)
            doc.close()

            # 提取章节标题
            chapters = self._extract_chapters(md_text)

            return {
                "markdown": md_text,
                "page_count": page_count,
                "chapters": chapters,
                "file_path": pdf_path,
                "page_mapping": page_text_mapping  # 字符偏移量→页码映射
            }

        except Exception as e:
            print(f"[PDFParser] 解析PDF失败 {pdf_path}: {e}")
            raise
    
    def _build_page_mapping(self, doc, md_text: str) -> List[Tuple[int, int]]:
        """
        建立字符偏移量→页码映射表
        返回一个 [(char_offset, page_number), ...] 的列表，有序按 char_offset

        Args:
            doc: pymupdf文档对象
            md_text: 完整的markdown文本

        Returns:
            [(char_offset, page_num), ...] 映射表
        """
        mapping = []
        char_offset = 0

        for page_num in range(doc.page_count):
            page = doc[page_num]
            page_text = page.get_text()
            page_char_count = len(page_text)

            # 记录该页的起始字符偏移量
            mapping.append((char_offset, page_num + 1))
            char_offset += page_char_count

        return mapping

    def _extract_chapters(self, md_text: str) -> List[Dict[str, Any]]:
        """提取Markdown章节结构"""
        chapters = []
        # 匹配一级标题
        h1_pattern = r'^#\s+(.+)$'
        lines = md_text.split('\n')
        
        current_chapter = None
        current_content = []
        start_line = 0
        
        for i, line in enumerate(lines):
            h1_match = re.match(h1_pattern, line)
            if h1_match:
                # 保存上一个章节
                if current_chapter:
                    chapters.append({
                        "title": current_chapter,
                        "content": '\n'.join(current_content),
                        "start_line": start_line,
                        "end_line": i - 1
                    })
                
                # 开始新章节
                current_chapter = h1_match.group(1)
                current_content = []
                start_line = i
            else:
                current_content.append(line)
        
        # 保存最后一个章节
        if current_chapter:
            chapters.append({
                "title": current_chapter,
                "content": '\n'.join(current_content),
                "start_line": start_line,
                "end_line": len(lines) - 1
            })
        
        return chapters
    
    def clean_text(self, text: str, language: str = "zh") -> str:
        """
        清洗文本，移除噪声
        
        Args:
            text: 待清洗文本
            language: 语言类型 (zh/en)
        
        Returns:
            清洗后的文本
        """
        # 移除页眉页脚模式
        patterns_to_remove = [
            r'第\s*\d+\s*页',  # 中文页码
            r'Page\s*\d+',  # 英文页码
            r'^\s*参考文献\s*$',  # 参考文献标题行
            r'^\s*References\s*$',
            r'^\s*目录\s*$',
            r'^\s*Contents\s*$',
        ]
        
        # 中文指南特有噪声
        if language == "zh":
            patterns_to_remove.extend([
                r'编委名单.*',
                r'会议通知.*',
                r'^\s*中华医学会.*分会\s*$',
            ])
        
        cleaned = text
        for pattern in patterns_to_remove:
            cleaned = re.sub(pattern, '', cleaned, flags=re.MULTILINE)
        
        # 移除多余空白
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
        cleaned = re.sub(r' {2,}', ' ', cleaned)
        
        # 移除空白图表占位符
        cleaned = re.sub(r'\[图片\].*', '', cleaned)
        cleaned = re.sub(r'\[Figure.*\]', '', cleaned)
        
        return cleaned.strip()


class ChunkSplitter:
    """文档Chunk切分器"""
    
    def __init__(self, window: int = CHUNK_WINDOW, overlap: int = CHUNK_OVERLAP,
                 min_token: int = MIN_CHUNK_TOKEN):
        self.window = window
        self.overlap = overlap
        self.min_token = min_token
        # 循证关键词 - 需要独立分块
        self.evidence_keywords = [
            "推荐等级", "证据级别", "RCT", "Meta分析", "结论",
            "recommendation", "evidence level", "conclusion",
            "Recommendation Class", "Evidence Grade"
        ]
    
    def split_document(self, doc_info: Dict[str, Any], meta: Dict[str, Any]) -> List[ChunkMeta]:
        """
        对文档进行分层Chunk切分

        Args:
            doc_info: PDF解析结果
            meta: 文档元数据

        Returns:
            Chunk列表
        """
        md_text = doc_info["markdown"]
        chapters = doc_info["chapters"]
        page_mapping = doc_info.get("page_mapping", [])  # 字符偏移量→页码映射

        chunks = []
        chunk_idx = 0

        # 1. 按章节粗分割
        for chapter in chapters:
            chapter_title = chapter["title"]
            chapter_content = self._clean_chapter(chapter["content"])

            # 2. 章节内滑动窗口切分
            chapter_chunks = self._split_by_sliding_window(
                chapter_content, chunk_idx, meta, chapter_title, page_mapping
            )
            chunks.extend(chapter_chunks)
            chunk_idx += len(chapter_chunks)

        # 3. 处理无章节的文档
        if not chapters:
            chunks = self._split_by_sliding_window(
                self._clean_chapter(md_text), 0, meta, None, page_mapping
            )

        # 4. 过小片段合并兜底
        chunks = self._merge_small_chunks(chunks)

        return chunks
    
    def _split_by_sliding_window(self, text: str, start_idx: int,
                                  meta: Dict, chapter_title: Optional[str],
                                  page_mapping: List[Tuple[int, int]] = None) -> List[ChunkMeta]:
        """滑动窗口切分"""
        # 简化的token计数（使用字符数近似）
        # 实际应使用tokenizer精确计算
        chars_per_token = 4  # 中英文平均估计
        window_chars = self.window * chars_per_token
        overlap_chars = self.overlap * chars_per_token

        chunks = []
        text_len = len(text)
        start = 0
        idx = start_idx

        while start < text_len:
            end = min(start + window_chars, text_len)
            chunk_text = text[start:end]

            # 检查是否包含循证关键词 - 强制断点
            if self._contains_evidence_keyword(chunk_text):
                # 找到关键词位置，从该位置切分
                kw_pos = self._find_evidence_keyword_pos(chunk_text)
                if kw_pos > 0:
                    # 关键词前的内容作为独立块
                    pre_text = chunk_text[:kw_pos].strip()
                    if len(pre_text) >= self.min_token * chars_per_token:
                        chunks.append(self._build_chunk(
                            pre_text, idx, meta, chapter_title,
                            page=self._estimate_page(start, meta, page_mapping)
                        ))
                        idx += 1

                    # 关键词开始的内容作为新块
                    chunk_text = chunk_text[kw_pos:]

            chunks.append(self._build_chunk(
                chunk_text, idx, meta, chapter_title,
                page=self._estimate_page(start, meta, page_mapping)
            ))
            idx += 1

            # 滑动窗口前进
            start = end - overlap_chars
            if start < 0:
                start = 0

        return chunks
    
    def _clean_chapter(self, content: str) -> str:
        """清洗章节内容"""
        # 移除章节内的噪声
        cleaned = content
        # 移除表格标记（保留表格内容）
        cleaned = re.sub(r'^---+\s*$', '', cleaned)
        cleaned = re.sub(r'^\|.*\|$', '', cleaned, flags=re.MULTILINE)  # 可根据需要保留
        return cleaned.strip()
    
    def _contains_evidence_keyword(self, text: str) -> bool:
        """检查是否包含循证关键词"""
        text_lower = text.lower()
        for kw in self.evidence_keywords:
            if kw.lower() in text_lower:
                return True
        return False
    
    def _find_evidence_keyword_pos(self, text: str) -> int:
        """找到循证关键词位置"""
        text_lower = text.lower()
        for kw in self.evidence_keywords:
            pos = text_lower.find(kw.lower())
            if pos >= 0:
                return pos
        return 0
    
    def _estimate_page(self, char_pos: int, meta: Dict, page_mapping: List[Tuple[int, int]] = None) -> str:
        """根据字符位置估算页码"""
        if not page_mapping:
            return "1"

        # 从 page_mapping 中获取所有偏移量列表
        offsets = [m[0] for m in page_mapping]

        # 使用 bisect_right 找到 char_pos 所在的页码
        idx = bisect_right(offsets, char_pos) - 1
        if idx < 0:
            return "1"
        if idx >= len(page_mapping):
            return str(page_mapping[-1][1])

        return str(page_mapping[idx][1])
    
    def _build_chunk(self, text: str, idx: int, meta: Dict, 
                     chapter_title: Optional[str], page: str) -> ChunkMeta:
        """构建Chunk元数据"""
        return ChunkMeta(
            chunk_id=f"chunk_{meta['doc_id']}_{idx}",
            doc_id=meta["doc_id"],
            source_type=meta["source_type"],
            pmid=meta.get("pmid"),
            cn_guide_code=meta.get("cn_guide_code"),
            title=meta["title"],
            publish_date=str(meta.get("publish_year", "")),
            evidence_level=meta.get("evidence_level", ""),
            language=meta["language"],
            page=page,
            chunk_index=idx,
            disease_tag=meta.get("disease_tags", []),
            chapter_title=chapter_title,
            text=text.strip()
        )
    
    def _merge_small_chunks(self, chunks: List[ChunkMeta]) -> List[ChunkMeta]:
        """合并过小片段"""
        chars_per_token = 4
        min_chars = self.min_token * chars_per_token
        
        merged = []
        i = 0
        
        while i < len(chunks):
            current = chunks[i]
            text_len = len(current["text"])
            
            # 如果当前chunk太小且后面还有chunk，尝试合并
            if text_len < min_chars and i + 1 < len(chunks):
                # 检查是否可以合并（同章节）
                next_chunk = chunks[i + 1]
                if current.get("chapter_title") == next_chunk.get("chapter_title"):
                    # 合并文本
                    merged_text = current["text"] + "\n" + next_chunk["text"]
                    current["text"] = merged_text
                    # 跳过下一个chunk
                    i += 2
                    merged.append(current)
                    continue
            
            merged.append(current)
            i += 1
        
        return merged
    
    def split_table(self, table_text: str, meta: Dict, idx: int) -> ChunkMeta:
        """处理表格数据 - 完整保留不拆分"""
        return ChunkMeta(
            chunk_id=f"chunk_{meta['doc_id']}_{idx}_table",
            doc_id=meta["doc_id"],
            source_type=meta["source_type"],
            pmid=meta.get("pmid"),
            cn_guide_code=meta.get("cn_guide_code"),
            title=meta["title"],
            publish_date=str(meta.get("publish_year", "")),
            evidence_level=meta.get("evidence_level", ""),
            language=meta["language"],
            page=meta.get("page", "1"),
            chunk_index=idx,
            disease_tag=meta.get("disease_tags", []),
            chapter_title="表格数据",
            text=table_text.strip()
        )


class DocumentProcessor:
    """文档处理流水线"""
    
    def __init__(self):
        self.parser = PDFParser()
        self.splitter = ChunkSplitter()
    
    def process_pdf(self, pdf_path: str, meta: Dict[str, Any]) -> List[ChunkMeta]:
        """
        处理单个PDF文档
        
        Args:
            pdf_path: PDF文件路径
            meta: 文档元数据
        
        Returns:
            Chunk列表
        """
        # 1. 解析PDF
        doc_info = self.parser.parse_pdf_to_markdown(pdf_path)
        
        # 2. 清洗文本
        doc_info["markdown"] = self.parser.clean_text(
            doc_info["markdown"], 
            language=meta.get("language", "zh")
        )
        
        # 3. 切分Chunk
        chunks = self.splitter.split_document(doc_info, meta)
        
        print(f"[DocProcessor] 处理完成: {pdf_path}, 生成 {len(chunks)} 个chunks")
        return chunks
    
    def process_batch(self, doc_ids: List[str]) -> Dict[str, List[ChunkMeta]]:
        """
        批量处理文档
        
        Args:
            doc_ids: 文档ID列表
        
        Returns:
            文档ID到Chunk列表的映射
        """
        results = {}
        for doc_id in doc_ids:
            try:
                # 获取文档元数据
                meta = article_dao.get_by_doc_id(doc_id)
                if not meta:
                    print(f"[DocProcessor] 未找到文档元数据: {doc_id}")
                    continue
                
                file_path = meta.get("file_path", "")
                if not file_path or not os.path.exists(file_path):
                    print(f"[DocProcessor] 文件不存在: {file_path}")
                    continue
                
                chunks = self.process_pdf(file_path, meta)
                results[doc_id] = chunks
                
            except Exception as e:
                print(f"[DocProcessor] 处理失败 {doc_id}: {e}")
                continue
        
        return results
    
    def save_chunks_to_json(self, chunks: List[ChunkMeta], output_path: str):
        """保存chunks到JSON文件"""
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(chunks, f, ensure_ascii=False, indent=2)
        print(f"[DocProcessor] 已保存 {len(chunks)} 个chunks到 {output_path}")


# 全局实例
pdf_parser = PDFParser()
chunk_splitter = ChunkSplitter()
doc_processor = DocumentProcessor()