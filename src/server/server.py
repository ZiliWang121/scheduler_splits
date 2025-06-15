#!/usr/bin/env python3
import sys
import os
import time
import re
import socket
from http.server import HTTPServer, BaseHTTPRequestHandler
from configparser import ConfigParser

import mpsched
import numpy as np
import pandas as pd

def main(argv):
    # ——— 1) 读取配置 —————————————————————
    cfg = ConfigParser()
    cfg.read('config.ini')
    IP   = cfg.get('server','ip')
    PORT = cfg.getint('server','port')
    FILE = cfg.get('file','file')
    FILES = ["64kb.dat","2mb.dat","8mb.dat","64mb.dat"]
    num_iterations = 150

    # ——— 2) 解析命令行参数 —————————————————
    # argv[0] = num_iterations, argv[1] = FILE (或 "random")
    if len(argv) >= 1:
        num_iterations = int(argv[0])
    if len(argv) >= 2:
        FILE = argv[1]
    print(f"FILE={FILE}, num_iterations={num_iterations}")

    # ——— 3) 初始化度量容器 —————————————————
    performance_metrics = []
    np.random.seed(42)
    iteration = 0

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal iteration, performance_metrics, FILE
            # 随机选择 FILE2（保持和原 client.py 一致）
            if FILE == "random" and num_iterations > 150:
                FILE2 = np.random.choice(FILES, p=[0,0.9,0,0.1])
            elif FILE == "random":
                FILE2 = np.random.choice(FILES, p=[0.3,0.35,0.3,0.05])
            else:
                FILE2 = FILE

            # 1) 预处理
            ooq = [0,0,0]
            length = int(self.headers.get('Content-Length', 0))
            fd = self.request.fileno()
            mpsched.persist_state(fd)

            # 2) 接收数据并采样子流状态
            start = time.time()
            received = 0
            subs = None
            while received < length:
                subs = mpsched.get_sub_info(fd)
                chunk = self.rfile.read(min(2048, length - received))
                if not chunk:
                    break
                received += len(chunk)
            stop = time.time()

            # 3) 只有 iteration >= 30 时才记录指标（和原版一致）
            if iteration >= 30 and subs is not None:
                for s in subs:
                    path_mask = s[8]
                    val = s[7]
                    if path_mask == 16842762:
                        ooq[0] = val
                    elif path_mask == 33685514:
                        ooq[1] = val
                    else:
                        ooq[2] = val
                completion_time = stop - start
                # 文件大小解析
                if FILE2.endswith("kb.dat"):
                    size_mb = int(re.findall(r'\d+', FILE2)[0]) / 1000
                else:
                    size_mb = int(re.findall(r'\d+', FILE2)[0])
                throughput = size_mb / completion_time

                performance_metrics.append({
                    "completion time": completion_time,
                    "throughput": throughput,
                    "out-of-order 4G": ooq[0],
                    "out-of-order 5G": ooq[1],
                    "out-of-order WLAN": ooq[2],
                })

            iteration += 1
            # 回复客户端
            self.send_response(200)
            self.end_headers()

            # 4) 达到次数后写 CSV 并退出
            if iteration >= num_iterations:
                df = pd.DataFrame(performance_metrics)
                df.to_csv("server_metrics.csv", index=False)
                print(f"Finished {iteration} iterations, saved server_metrics.csv")
                os._exit(0)

        def log_message(self, fmt, *args):
            pass  # 关闭默认访问日志

    # ——— 4) 启动 HTTP 服务器 —————————————————
    print(f"Starting upload-receive server on {IP}:{PORT}")
    HTTPServer((IP, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main(sys.argv[1:])
