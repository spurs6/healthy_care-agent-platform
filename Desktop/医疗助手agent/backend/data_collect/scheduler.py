"""
OpenEvidence 临床证据助手 - 定时任务调度模块
管理月度增量更新任务
"""
import uuid
from datetime import datetime
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config import MONTHLY_UPDATE_DAY, MONTHLY_UPDATE_HOUR
from backend.data_collect.pubmed_api import pubmed_fetcher
from backend.data_collect.offline_crawler import europepmc_crawler
from backend.db_store import task_dao


class DataUpdateScheduler:
    """数据增量更新调度器"""
    
    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.is_running = False
    
    def start(self):
        """启动调度器"""
        if self.is_running:
            return
        
        # 添加月度更新任务
        self.scheduler.add_job(
            self.monthly_update_job,
            CronTrigger(day=MONTHLY_UPDATE_DAY, hour=MONTHLY_UPDATE_HOUR),
            id='monthly_pubmed_update',
            name='月度PubMed增量更新',
            replace_existing=True
        )
        
        self.scheduler.start()
        self.is_running = True
        print(f"[Scheduler] 定时任务已启动，每月{MONTHLY_UPDATE_DAY}日{MONTHLY_UPDATE_HOUR}点执行")
    
    def stop(self):
        """停止调度器"""
        if self.is_running:
            self.scheduler.shutdown()
            self.is_running = False
            print("[Scheduler] 定时任务已停止")
    
    def monthly_update_job(self):
        """月度增量更新任务"""
        task_id = f"monthly_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        print(f"[Scheduler] 开始执行月度增量更新任务: {task_id}")
        
        # 记录任务开始
        task_dao.create_task(task_id, "pubmed_monthly")
        
        try:
            # 执行PubMed增量获取
            articles = pubmed_fetcher.fetch_monthly_incremental(days=30)
            
            if articles:
                saved = pubmed_fetcher.save_to_database(articles)
                task_dao.update_task(
                    task_id, 
                    status="completed", 
                    processed=saved,
                    log=f"成功获取并保存{saved}篇增量文献"
                )
            else:
                task_dao.update_task(
                    task_id, 
                    status="completed", 
                    log="本月无新增文献"
                )
                
        except Exception as e:
            task_dao.update_task(
                task_id, 
                status="failed", 
                error=1,
                log=f"任务执行失败: {str(e)}"
            )
    
    def run_manual_update(self, source: str = "pubmed", days: int = 30) -> str:
        """
        手动触发增量更新

        Args:
            source: 数据源 (pubmed, europepmc)
            days: 获取最近N天的数据

        Returns:
            任务ID
        """
        task_id = f"manual_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        task_dao.create_task(task_id, "manual_import")

        try:
            if source == "pubmed":
                articles = pubmed_fetcher.fetch_monthly_incremental(days=days)
                saved = pubmed_fetcher.save_to_database(articles)
            elif source == "europepmc":
                stats = europepmc_crawler.batch_crawl_diseases(articles_per_disease=30)
                saved = sum(stats.values())
            else:
                raise ValueError(f"未支持的数据源: {source}，仅支持 pubmed 或 europepmc")

            task_dao.update_task(task_id, status="completed", processed=saved)
            return task_id

        except Exception as e:
            task_dao.update_task(task_id, status="failed", error=1, log=str(e))
            print(f"[Scheduler] 增量更新失败: {e}")
            return task_id

    def get_task_status(self, task_id: str) -> Optional[dict]:
        """按task_id获取任务状态"""
        return task_dao.get_by_task_id(task_id)


# 全局调度器实例
scheduler = DataUpdateScheduler()