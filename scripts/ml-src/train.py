#!/usr/bin/env python3
"""演练用训练脚本：只依赖 Python 标准库。

通过 TRAIN_MODE 注入不同故障：
  normal 正常训练；oom 内存持续增长；crash 数据集缺失；
  hang 卡住不退出；ckpt 加载损坏 checkpoint；disk 写满 checkpoint 目录。
"""
import json
import os
import pathlib
import sys
import time
import traceback

MODE = os.getenv("TRAIN_MODE", "normal")
CKPT = os.getenv("CKPT_PATH", "/ckpt/model.json")
DATA = os.getenv("DATA_PATH", "/data/train.json")


def log(msg):
    print(f"[train] {msg}", flush=True)


def load_data():
    log(f"loading dataset: {DATA}")
    with open(DATA, encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(step, loss):
    pathlib.Path(os.path.dirname(CKPT)).mkdir(parents=True, exist_ok=True)
    tmp = CKPT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"step": step, "loss": loss, "weights": [0.1, 0.2, 0.3]}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CKPT)
    log(f"checkpoint saved: {CKPT}")


def train(steps=200):
    load_data()
    weight = 0.0
    loss = 0.0
    for step in range(1, steps + 1):
        loss = abs(1.0 - weight) / step
        weight += 0.01
        if step % 10 == 0:
            log(f"step={step} loss={loss:.4f} lr=0.001")
        time.sleep(0.05)
    save_checkpoint(steps, loss)


def main():
    log(f"mode={MODE} pid={os.getpid()}")
    if MODE == "oom":
        train(steps=20)
        chunks = []
        for i in range(1, 40):
            chunks.append(bytearray(32 * 1024 * 1024))
            log(f"allocated {i * 32}MB (batch/cache growing)")
            time.sleep(0.4)
    elif MODE == "crash":
        log("step=10 loss=0.9100")
        log("loading next shard: /data/train.csv")
        with open("/data/train.csv", encoding="utf-8") as f:
            f.read()
    elif MODE == "hang":
        log("step=10 loss=0.9100")
        log("waiting for next batch from dataloader (rank 0)...")
        while True:
            time.sleep(60)
    elif MODE == "ckpt":
        log(f"resuming from checkpoint: {CKPT}")
        with open(CKPT, encoding="utf-8") as f:
            state = json.load(f)
        log(f"resumed state={state}")
    elif MODE == "disk":
        pathlib.Path("/ckpt").mkdir(parents=True, exist_ok=True)
        for i in range(1, 200):
            shard = pathlib.Path(f"/ckpt/ckpt-{i:04d}.bin")
            with open(shard, "wb") as f:
                f.write(b"0" * (8 * 1024 * 1024))
                f.flush()
                os.fsync(f.fileno())
            log(f"wrote checkpoint shard {i} (8MB), total {i * 8}MB")
            time.sleep(0.1)
    else:
        train()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
