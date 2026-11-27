#!/usr/bin/env python3
"""渲染 Chaos 模板：把 __EXPIRES_AT__ 替换为 now + N 分钟的 UTC RFC3339 时间。"""
import argparse
import datetime
import pathlib
import sys


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--template", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--expires-minutes", type=int, default=3)
    p.add_argument("--duration", default=None, help="可选：替换模板中的 duration 字段值")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="可选：替换模板中的 __KEY__ 占位符")
    a = p.parse_args()

    src = pathlib.Path(a.template)
    if not src.is_file():
        print(f"模板不存在: {src}", file=sys.stderr)
        return 1

    text = src.read_text(encoding="utf-8")
    expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=a.expires_minutes)
    text = text.replace("__EXPIRES_AT__", expires.strftime("%Y-%m-%dT%H:%M:%SZ"))

    if a.duration:
        # 只替换 duration: "..." 这一行，保留其余模板
        import re
        text = re.sub(r'(?m)^(\s*duration:\s*)"[^"]*"', rf'\g<1>"{a.duration}"', text)

    for item in a.set:
        if "=" not in item:
            print(f"--set 需要 KEY=VALUE: {item}", file=sys.stderr)
            return 1
        key, value = item.split("=", 1)
        text = text.replace(f"__{key}__", value)

    out = pathlib.Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
