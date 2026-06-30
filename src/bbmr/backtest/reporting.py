import json
from pathlib import Path

import pandas as pd
import yaml


MANUAL_ENGINE = "manual_event_loop"
TRAILING_ENGINE = "trailing_event_loop"
TRAILING_PORTFOLIO_ENGINE = "trailing_portfolio_event_loop"


def write_reports(result, config, out_dir: str | Path, *, overwrite: bool = False, run_id: str | None = None, engine: str | None = None) -> Path:
    path = Path(out_dir)
    files = ["summary.csv", "trades.csv", "orders.csv", "equity_curve.csv", "config_snapshot.yaml", "run_metadata.json"]
    if path.exists():
        if not overwrite:
            raise FileExistsError(f"output directory exists: {path}")
        for name in files:
            target = path / name
            if target.exists():
                target.unlink()
    path.mkdir(parents=True, exist_ok=True)

    result.orders.to_csv(path / "orders.csv", index=False)
    result.trades.to_csv(path / "trades.csv", index=False)
    result.equity_curve.to_csv(path / "equity_curve.csv", index=False)
    summary = summarize_result(result, config, engine=engine)
    summary.to_csv(path / "summary.csv", index=False)
    with (path / "config_snapshot.yaml").open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config.model_dump(), handle, sort_keys=True)
    with (path / "run_metadata.json").open("w", encoding="utf-8") as handle:
        json.dump({"run_id": run_id or path.name, "engine": engine or _engine_name(config)}, handle, indent=2)
    return path


def summarize_result(result, config, *, engine: str | None = None) -> pd.DataFrame:
    equity = result.equity_curve["equity"] if not result.equity_curve.empty else pd.Series([0.0])
    init_cash = float(equity.iloc[0]) if len(equity) else 0.0
    final_equity = float(equity.iloc[-1]) if len(equity) else init_cash
    drawdown = equity / equity.cummax() - 1 if len(equity) else pd.Series([0.0])
    trades = result.trades
    wins = trades[trades["net_pnl"] > 0] if not trades.empty else trades
    losses = trades[trades["net_pnl"] < 0] if not trades.empty else trades
    profit_factor = 0.0 if losses.empty else float(wins["net_pnl"].sum() / abs(losses["net_pnl"].sum()))
    return pd.DataFrame(
        [
            {
                "symbol": result.symbol,
                "start": result.equity_curve["timestamp"].iloc[0] if not result.equity_curve.empty else None,
                "end": result.equity_curve["timestamp"].iloc[-1] if not result.equity_curve.empty else None,
                "init_cash": init_cash,
                "final_equity": final_equity,
                "total_return_pct": 0.0 if init_cash == 0 else (final_equity / init_cash - 1) * 100,
                "max_drawdown_pct": float(drawdown.min() * 100),
                "total_trades": len(trades),
                "closed_trades": len(trades),
                "win_rate_pct": 0.0 if trades.empty else len(wins) / len(trades) * 100,
                "profit_factor": profit_factor,
                "avg_r": 0.0 if trades.empty else float(trades["r_multiple"].mean()),
                "max_loss_r": 0.0 if trades.empty else float(trades["r_multiple"].min()),
                "engine": engine or _engine_name(config),
                "decision_engine_commit": "local",
            }
        ]
    )


def _engine_name(config) -> str:
    if config.strategy.name == "bbmr_trailing_stop_v1":
        return TRAILING_ENGINE
    return MANUAL_ENGINE
