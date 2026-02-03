from __future__ import annotations

import argparse
import json
import os
import time

DEFAULT_STATE_PATH = os.getenv("BOTCTL_STATE_PATH", ".state/botctl.json")


def _read(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write(path: str, data: dict) -> None:
    d = os.path.dirname(path) or "."
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp, path)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Control plane for arb-scanner daemon (simple file-based switch).")
    p.add_argument("--state-path", default=DEFAULT_STATE_PATH)

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")

    on = sub.add_parser("on")
    on.add_argument("--mode", choices=["alerts", "paper"], default="paper")

    off = sub.add_parser("off")

    setp = sub.add_parser("set")
    setp.add_argument("--bankroll", type=float)
    setp.add_argument("--max-per-trade", type=float)
    setp.add_argument("--min-buf-edge", type=float)
    setp.add_argument("--enabled", type=int, choices=[0, 1])
    setp.add_argument("--mode", choices=["alerts", "paper", "off"])

    return p.parse_args()


def main() -> int:
    args = parse_args()
    st = _read(args.state_path)
    st.setdefault("enabled", False)
    st.setdefault("mode", "off")  # off | alerts | paper
    st.setdefault("bankroll", 1000.0)
    st.setdefault("max_per_trade", 50.0)
    st.setdefault("min_buf_edge", 0.02)
    st["updated_at"] = int(time.time())

    if args.cmd == "status":
        print(json.dumps(st, indent=2, sort_keys=True))
        return 0

    if args.cmd == "on":
        st["enabled"] = True
        st["mode"] = args.mode
        _write(args.state_path, st)
        print(f"[botctl] enabled mode={st['mode']} state={args.state_path}")
        return 0

    if args.cmd == "off":
        st["enabled"] = False
        st["mode"] = "off"
        _write(args.state_path, st)
        print(f"[botctl] disabled state={args.state_path}")
        return 0

    if args.cmd == "set":
        if args.bankroll is not None:
            st["bankroll"] = float(args.bankroll)
        if args.max_per_trade is not None:
            st["max_per_trade"] = float(args.max_per_trade)
        if args.min_buf_edge is not None:
            st["min_buf_edge"] = float(args.min_buf_edge)
        if args.enabled is not None:
            st["enabled"] = bool(int(args.enabled))
        if args.mode is not None:
            st["mode"] = args.mode
        _write(args.state_path, st)
        print(f"[botctl] updated state={args.state_path}")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
