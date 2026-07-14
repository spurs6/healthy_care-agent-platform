"""
启动所有服务脚本
1. 嵌入服务
2. 后端API
3. 前端
"""
import subprocess
import time
import os
import sys
import requests
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 使用AI虚拟环境
PYTHON_EXE = "E:/anaconda/envs/AI/python.exe"


def check_port(port):
    """检查端口是否被占用"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', port))
    sock.close()
    return result == 0


def wait_for_service(url, timeout=30):
    """等待服务启动"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return True
        except:
            pass
        time.sleep(1)
    return False


def main():
    print("=" * 60)
    print("启动医疗助手服务")
    print("=" * 60)
    
    # 1. 先关闭已有服务
    print("\n[准备] 关闭已有服务...")
    os.system("taskkill /F /IM python.exe /FI \"WINDOWTITLE eq *embedding*\" 2>nul")
    os.system("taskkill /F /IM python.exe /FI \"WINDOWTITLE eq *backend*\" 2>nul")
    time.sleep(2)
    
    # 2. 启动嵌入服务
    print("\n[1/3] 启动嵌入服务 (端口8100)...")
    if check_port(8100):
        print("    端口8100已被占用，跳过")
    else:
        embedding_proc = subprocess.Popen(
            [PYTHON_EXE, "embedding_service/main.py"],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )
        
        if wait_for_service("http://localhost:8100/health", timeout=30):
            print("    嵌入服务启动成功!")
        else:
            print("    嵌入服务启动失败!")
            return
    
    # 3. 重建向量库
    print("\n[2/3] 重建向量索引...")
    rebuild_result = subprocess.run(
        [PYTHON_EXE, "scripts/rebuild_vector_db.py"],
        cwd=BASE_DIR,
        capture_output=True,
        text=True
    )
    print(rebuild_result.stdout)
    if rebuild_result.returncode != 0:
        print(rebuild_result.stderr)
    
    # 4. 启动后端
    print("\n[3/3] 启动后端服务 (端口8000)...")
    if check_port(8000):
        print("    端口8000已被占用，跳过")
    else:
        backend_proc = subprocess.Popen(
            [PYTHON_EXE, "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=BASE_DIR,
            creationflags=subprocess.CREATE_NEW_CONSOLE
        )

        if wait_for_service("http://localhost:8000/docs", timeout=30):
            print("    后端服务启动成功!")
        else:
            print("    后端服务启动失败!")
    
    # 5. 启动前端
    print("\n[4/4] 启动前端服务 (端口5173)...")
    frontend_dir = os.path.join(BASE_DIR, "frontend")
    
    # 检查是否需要安装依赖
    if not os.path.exists(os.path.join(frontend_dir, "node_modules")):
        print("    安装前端依赖...")
        subprocess.run(["npm", "install"], cwd=frontend_dir, shell=True)
    
    frontend_proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=frontend_dir,
        shell=True,
        creationflags=subprocess.CREATE_NEW_CONSOLE
    )
    
    time.sleep(5)
    
    # 总结
    print("\n" + "=" * 60)
    print("服务启动完成!")
    print("=" * 60)
    print("\n访问地址:")
    print("  前端: http://localhost:5183")
    print("  后端API文档: http://localhost:8000/docs")
    print("  嵌入服务: http://localhost:8100")
    print("\n按任意键退出此窗口（服务将继续运行）...")
    input()


if __name__ == "__main__":
    main()