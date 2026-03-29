"""
Advanced Optimization Engine
- NSGA-II Multi-Objective Optimization (Pareto front)
- Bayesian Optimization (TPE via Optuna)
"""

import copy
import random
import math
import numpy as np
from typing import Optional, Callable

from auto_research import (
    ENTRY_GENES, EXIT_GENES, LONG_GENES, SHORT_GENES, FILTER_GENES,
    dna_to_code, dna_to_description, random_params, score_strategy,
    _sync_bidirectional,
)
from backtest_engine import BacktestEngine, StrategyConfig, evaluate
from optimizer import walk_forward


# ═══════════════════════════════════════════════════
# SHARED: DNA evaluation
# ═══════════════════════════════════════════════════

def evaluate_dna(candles, dna):
    """Evaluate a DNA, return metrics dict or None."""
    from llm_pipeline import compile_strategy, validate_strategy

    try:
        code = dna_to_code(dna)
        strategy_fn, err = compile_strategy(code)
        if err:
            return None

        ok, err = validate_strategy(strategy_fn, candles, 20)
        if not ok:
            return None

        config = StrategyConfig(
            initial_capital=10000, position_size_pct=10,
            stop_loss_pct=dna["sl"], take_profit_pct=dna["tp"],
        )
        engine = BacktestEngine(config)
        trades = engine.run(candles, strategy_fn)
        metrics = evaluate(trades, config.initial_capital, engine.equity_curve)

        wf_data = None
        wf_overfit = None
        try:
            wf = walk_forward(candles, strategy_fn, config)
            wf_overfit = wf["overfit_ratio"]
            wf_data = {
                "train_roi": wf["train"].get("roi_pct", 0),
                "test_roi": wf["test"].get("roi_pct", 0),
                "overfit_ratio": wf["overfit_ratio"],
            }
        except Exception:
            pass

        sc = score_strategy(metrics, wf_overfit)
        if sc <= -999:
            return None

        return {
            "dna": dna,
            "code": code,
            "metrics": metrics,
            "score": sc,
            "walk_forward": wf_data,
            "description": dna_to_description(dna),
        }
    except Exception:
        return None


def _apply_gene_modifications(base_dna, mods):
    """Apply add_genes, remove_genes, and custom_genes to base_dna.

    Syncs all changes to long_genes/short_genes for bidirectional strategies.
    Returns list of custom gene names (for cleanup).
    """
    # --- Add standard genes ---
    for gene_info in mods.get("add_genes", []):
        name = gene_info["name"]
        if name in ENTRY_GENES:
            params = random_params(ENTRY_GENES[name]["params"])
            base_dna["entry_genes"].append((name, params))
            if base_dna.get("side") == "both" and "long_genes" in base_dna:
                if name in LONG_GENES:
                    base_dna["long_genes"].append((name, params))
                elif name in SHORT_GENES:
                    base_dna["short_genes"].append((name, params))
                if name in FILTER_GENES:
                    if (name, params) not in base_dna.get("long_genes", []):
                        base_dna["long_genes"].append((name, params))
                    if (name, params) not in base_dna.get("short_genes", []):
                        base_dna["short_genes"].append((name, params))

    # --- Remove genes ---
    remove_set = set(mods.get("remove_genes", []))
    if remove_set:
        base_dna["entry_genes"] = [(n, p) for n, p in base_dna["entry_genes"] if n not in remove_set]
        if base_dna.get("side") == "both":
            if "long_genes" in base_dna:
                base_dna["long_genes"] = [(n, p) for n, p in base_dna["long_genes"] if n not in remove_set]
            if "short_genes" in base_dna:
                base_dna["short_genes"] = [(n, p) for n, p in base_dna["short_genes"] if n not in remove_set]

    # --- Register custom genes ---
    custom_gene_names = []
    for cg in mods.get("custom_genes", []):
        gname = f"custom_{cg['name']}"
        cg_side = cg.get("side", "long")
        if cg_side in ("做多", "long"):
            gene_type = "long"
        elif cg_side in ("做空", "short"):
            gene_type = "short"
        else:
            gene_type = "filter"
        ENTRY_GENES[gname] = {
            "desc": cg.get("desc", cg["name"]),
            "params": cg.get("params", {}),
            "code": lambda p, c=cg: c["code"],
            "setup": lambda p, c=cg: c["setup"],
            "null_check": cg.get("null_check", "False"),
            "min_bars": lambda p, c=cg: c.get("min_bars", 50),
            "type": gene_type,
        }
        custom_gene_names.append(gname)
        base_dna["entry_genes"].append((gname, {}))

        if base_dna.get("side") == "both" and "long_genes" in base_dna:
            if gene_type == "long":
                base_dna["long_genes"].append((gname, {}))
            elif gene_type == "short":
                base_dna["short_genes"].append((gname, {}))
            else:
                base_dna["long_genes"].append((gname, {}))
                base_dna["short_genes"].append((gname, {}))

    return custom_gene_names


def _cleanup_custom_genes(custom_gene_names):
    """Remove temporarily registered custom genes."""
    for gname in custom_gene_names:
        ENTRY_GENES.pop(gname, None)


def _build_dna_from_params(base_dna, params, mods=None):
    """Build a DNA dict from Optuna/NSGA-II parameter dict."""
    mods = mods or {}
    param_overrides = mods.get("param_overrides", {})

    dna = copy.deepcopy(base_dna)
    dna["sl"] = params.get("sl", dna["sl"])
    dna["tp"] = params.get("tp", dna["tp"])

    # Gene parameters
    for idx, (gene_name, _) in enumerate(dna["entry_genes"]):
        if gene_name in ENTRY_GENES:
            gene_params = {}
            ranges = param_overrides.get(gene_name, ENTRY_GENES[gene_name].get("params", {}))
            for pname, pvals in ranges.items():
                key = f"g{idx}_{pname}"
                if key in params:
                    gene_params[pname] = params[key]
                else:
                    gene_params[pname] = pvals[0] if isinstance(pvals, list) else pvals
            dna["entry_genes"][idx] = (gene_name, gene_params)

    # Exit gene
    if "exit_gene" in params:
        exit_name = params["exit_gene"]
        if exit_name in EXIT_GENES:
            exit_params = random_params(EXIT_GENES[exit_name].get("params", {}))
            dna["exit_gene"] = (exit_name, exit_params)

    # Make sure bidirectional genes are perfectly synced with entry_genes
    _sync_bidirectional(dna)

    return dna


# ═══════════════════════════════════════════════════
# NSGA-II Multi-Objective Optimization
# ═══════════════════════════════════════════════════

def nsga2_optimize(candles, base_dna, modifications=None, pop_size=40, n_gen=20, on_progress=None):
    """
    NSGA-II multi-objective optimization.
    Objectives: maximize ROI, maximize Sharpe, minimize max drawdown.
    Returns: list of Pareto-optimal results.
    """
    from pymoo.core.problem import Problem
    from pymoo.algorithms.moo.nsga2 import NSGA2
    from pymoo.optimize import minimize as pymoo_minimize
    from pymoo.operators.crossover.sbx import SBX
    from pymoo.operators.mutation.pm import PM
    from pymoo.termination import get_termination

    mods = modifications or {}

    # Register custom genes
    custom_gene_names = _apply_gene_modifications(base_dna, mods)

    sl_range = mods.get("sl_range", [1.0, 1.5, 2.0, 3.0])
    tp_range = mods.get("tp_range", [2.0, 4.0, 6.0, 8.0])
    exit_genes = mods.get("exit_genes", [base_dna["exit_gene"][0]])

    # Build variable bounds
    var_names = []
    var_lower = []
    var_upper = []

    # SL/TP as continuous
    var_names.append("sl")
    var_lower.append(min(sl_range))
    var_upper.append(max(sl_range))

    var_names.append("tp")
    var_lower.append(min(tp_range))
    var_upper.append(max(tp_range))

    # Gene parameters
    param_overrides = mods.get("param_overrides", {})
    for idx, (gene_name, _) in enumerate(base_dna["entry_genes"]):
        if gene_name in ENTRY_GENES:
            ranges = param_overrides.get(gene_name, ENTRY_GENES[gene_name].get("params", {}))
            for pname, pvals in ranges.items():
                if isinstance(pvals, list) and len(pvals) > 1:
                    var_names.append(f"g{idx}_{pname}")
                    var_lower.append(min(pvals))
                    var_upper.append(max(pvals))

    n_var = len(var_names)
    xl = np.array(var_lower, dtype=float)
    xu = np.array(var_upper, dtype=float)

    # Cache for results
    all_results = []
    eval_count = [0]
    total_evals = pop_size * n_gen

    class StrategyProblem(Problem):
        def __init__(self):
            super().__init__(n_var=n_var, n_obj=3, n_constr=0, xl=xl, xu=xu)

        def _evaluate(self, X, out, *args, **kwargs):
            F = np.full((X.shape[0], 3), 1e6)  # penalty default

            for i, x in enumerate(X):
                eval_count[0] += 1
                params = {}
                for j, name in enumerate(var_names):
                    val = float(x[j])
                    # Snap gene params to nearest valid value
                    if name.startswith("g"):
                        parts = name.split("_", 1)
                        idx_str = parts[0][1:]
                        pname = parts[1]
                        gene_idx = int(idx_str)
                        gene_name = base_dna["entry_genes"][gene_idx][0]
                        pvals = ENTRY_GENES[gene_name]["params"].get(pname, [])
                        if isinstance(pvals, list) and pvals:
                            val = min(pvals, key=lambda v: abs(v - val))
                    params[name] = val

                # Round SL/TP to 0.5 steps
                params["sl"] = round(params["sl"] * 2) / 2
                params["tp"] = round(params["tp"] * 2) / 2
                if params["tp"] <= params["sl"]:
                    params["tp"] = params["sl"] + 1.0

                # Random exit gene
                params["exit_gene"] = random.choice(exit_genes)

                dna = _build_dna_from_params(base_dna, params, mods)
                result = evaluate_dna(candles, dna)

                if result:
                    m = result["metrics"]
                    roi = m.get("roi_pct", 0)
                    sharpe = m.get("sharpe_ratio", 0)
                    drawdown = abs(m.get("max_drawdown_pct", 100))

                    # pymoo minimizes, so negate ROI and Sharpe
                    F[i] = [-roi, -sharpe, drawdown]
                    all_results.append(result)

                if on_progress and eval_count[0] % 5 == 0:
                    on_progress(min(eval_count[0], total_evals), total_evals)

            out["F"] = F

    problem = StrategyProblem()

    algorithm = NSGA2(
        pop_size=pop_size,
        crossover=SBX(prob=0.9, eta=15),
        mutation=PM(eta=20),
        eliminate_duplicates=True,
    )

    termination = get_termination("n_gen", n_gen)

    res = pymoo_minimize(problem, algorithm, termination, seed=42, verbose=False)

    if on_progress:
        on_progress(total_evals, total_evals)

    # Deduplicate and return Pareto front results
    seen = set()
    pareto = []
    for r in all_results:
        m = r["metrics"]
        fp = (m.get("roi_pct", 0), m.get("win_rate", 0), m.get("total_trades", 0),
              m.get("profit_factor", 0), r["dna"]["sl"], r["dna"]["tp"])
        if fp not in seen:
            seen.add(fp)
            pareto.append(r)

    # Sort by score descending
    pareto.sort(key=lambda x: -x["score"])

    # Tag Pareto front membership
    if res.F is not None:
        pareto_set = set()
        for f in res.F:
            pareto_set.add((round(-f[0], 2), round(-f[1], 2), round(f[2], 2)))
        for r in pareto:
            m = r["metrics"]
            key = (round(m.get("roi_pct", 0), 2), round(m.get("sharpe_ratio", 0), 2),
                   round(abs(m.get("max_drawdown_pct", 0)), 2))
            r["pareto_front"] = key in pareto_set

    _cleanup_custom_genes(custom_gene_names)
    return pareto[:20]


# ═══════════════════════════════════════════════════
# Bayesian Optimization (TPE via Optuna)
# ═══════════════════════════════════════════════════

def bayesian_optimize(candles, base_dna, modifications=None, n_trials=100, on_progress=None):
    """
    Bayesian optimization using TPE (Tree-structured Parzen Estimator).
    Smarter than grid/random — learns which parameter regions are promising.
    Returns: top results sorted by score.
    """
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    mods = modifications or {}

    # Register custom genes
    custom_gene_names = _apply_gene_modifications(base_dna, mods)

    sl_range = mods.get("sl_range", [1.0, 1.5, 2.0, 3.0])
    tp_range = mods.get("tp_range", [2.0, 4.0, 6.0, 8.0])
    exit_genes = mods.get("exit_genes", [base_dna["exit_gene"][0]])

    all_results = []
    eval_count = [0]

    def objective(trial):
        eval_count[0] += 1
        params = {}

        # SL/TP
        params["sl"] = trial.suggest_categorical("sl", sl_range)
        params["tp"] = trial.suggest_categorical("tp", tp_range)
        if params["tp"] <= params["sl"]:
            return -9999  # invalid

        # Exit gene
        if len(exit_genes) > 1:
            params["exit_gene"] = trial.suggest_categorical("exit_gene", exit_genes)
        else:
            params["exit_gene"] = exit_genes[0]

        # Gene parameters
        param_overrides = mods.get("param_overrides", {})
        for idx, (gene_name, _) in enumerate(base_dna["entry_genes"]):
            if gene_name in ENTRY_GENES:
                ranges = param_overrides.get(gene_name, ENTRY_GENES[gene_name].get("params", {}))
                for pname, pvals in ranges.items():
                    if isinstance(pvals, list) and len(pvals) > 1:
                        params[f"g{idx}_{pname}"] = trial.suggest_categorical(
                            f"g{idx}_{pname}", pvals
                        )
                    elif isinstance(pvals, list):
                        params[f"g{idx}_{pname}"] = pvals[0]
                    else:
                        params[f"g{idx}_{pname}"] = pvals

        dna = _build_dna_from_params(base_dna, params)
        result = evaluate_dna(candles, dna)

        if on_progress and eval_count[0] % 5 == 0:
            on_progress(eval_count[0], n_trials)

        if result:
            all_results.append(result)
            # Optuna maximizes when direction="maximize"
            return result["score"]
        return -9999

    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
    )
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    if on_progress:
        on_progress(n_trials, n_trials)

    # Deduplicate
    seen = set()
    unique = []
    for r in all_results:
        m = r["metrics"]
        fp = (m.get("roi_pct", 0), m.get("win_rate", 0), m.get("total_trades", 0),
              m.get("profit_factor", 0), r["dna"]["sl"], r["dna"]["tp"])
        if fp not in seen:
            seen.add(fp)
            unique.append(r)

    unique.sort(key=lambda x: -x["score"])

    # Add convergence curve (best score over trials)
    convergence = []
    best_so_far = -9999
    for t in study.trials:
        if t.value is not None and t.value > best_so_far:
            best_so_far = t.value
        convergence.append({"trial": t.number + 1, "best_score": best_so_far})

    for r in unique:
        r["convergence"] = convergence

    _cleanup_custom_genes(custom_gene_names)
    return unique[:20]
