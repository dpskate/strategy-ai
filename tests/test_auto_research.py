"""
Unit tests for auto_research.py
測試 DNA 初始化、交叉、變異、評分函數
"""
import sys, os, copy, random
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auto_research import (
    ENTRY_GENES, EXIT_GENES, SL_TP_RANGES,
    LONG_GENES, SHORT_GENES, FILTER_GENES,
    random_params, create_strategy_dna, dna_to_code,
    mutate, crossover, score_strategy,
)


# ─── Helpers ───────────────────────────────────────────────────────────────

def good_metrics(**overrides):
    base = {
        "total_trades": 30,
        "wins": 18,
        "losses": 12,
        "win_rate": 60.0,
        "roi_pct": 20.0,
        "profit_factor": 1.8,
        "avg_rr": 1.5,
        "sharpe_ratio": 1.2,
        "max_drawdown_pct": 8.0,
        "long_trades": 15,
        "short_trades": 15,
    }
    base.update(overrides)
    return base


def dna_is_valid(dna):
    """Basic structural validity checks."""
    assert "entry_genes" in dna, "missing entry_genes"
    assert "exit_gene" in dna, "missing exit_gene"
    assert "sl" in dna and "tp" in dna, "missing sl/tp"
    assert len(dna["entry_genes"]) >= 1, "no entry genes"
    assert dna["tp"] > dna["sl"], f"tp({dna['tp']}) must be > sl({dna['sl']})"
    gene_name, params = dna["exit_gene"]
    assert gene_name in EXIT_GENES, f"unknown exit gene: {gene_name}"
    for name, p in dna["entry_genes"]:
        assert name in ENTRY_GENES, f"unknown entry gene: {name}"


# ─── random_params() ───────────────────────────────────────────────────────

class TestRandomParams:
    def test_returns_all_keys(self):
        param_ranges = {"fast": [5, 9, 12], "slow": [21, 26, 50]}
        p = random_params(param_ranges)
        assert set(p.keys()) == {"fast", "slow"}

    def test_values_from_list(self):
        param_ranges = {"level": [20, 25, 30]}
        for _ in range(20):
            p = random_params(param_ranges)
            assert p["level"] in [20, 25, 30]

    def test_empty_params(self):
        p = random_params({})
        assert p == {}


# ─── create_strategy_dna() ─────────────────────────────────────────────────

class TestCreateStrategyDNA:
    def test_valid_structure_long(self):
        dna = create_strategy_dna(direction="long")
        dna_is_valid(dna)
        assert dna["side"] == "long"

    def test_valid_structure_short(self):
        dna = create_strategy_dna(direction="short")
        dna_is_valid(dna)
        assert dna["side"] == "short"

    def test_valid_structure_both(self):
        dna = create_strategy_dna(direction="both")
        dna_is_valid(dna)
        assert dna["side"] == "both"
        assert "long_genes" in dna
        assert "short_genes" in dna

    def test_sl_tp_in_allowed_ranges(self):
        for _ in range(20):
            dna = create_strategy_dna(direction="long")
            assert dna["sl"] in SL_TP_RANGES["stop_loss_pct"]

    def test_tp_greater_than_sl(self):
        for _ in range(30):
            dna = create_strategy_dna()
            assert dna["tp"] > dna["sl"]

    def test_no_duplicate_entry_genes(self):
        # For single-direction strategies, entry_genes must have no duplicates.
        # For "both", long_genes and short_genes are each duplicate-free individually.
        for _ in range(20):
            dna = create_strategy_dna(direction="long")
            names = [g[0] for g in dna["entry_genes"]]
            assert len(names) == len(set(names)), f"duplicate genes: {names}"
        for _ in range(20):
            dna = create_strategy_dna(direction="both")
            for gene_list in (dna.get("long_genes", []), dna.get("short_genes", [])):
                names = [g[0] for g in gene_list]
                assert len(names) == len(set(names)), f"duplicate genes in sub-list: {names}"

    def test_allowed_entry_filter(self):
        allowed = {"ema_cross_up", "rsi_oversold"}
        for _ in range(20):
            dna = create_strategy_dna(allowed_entry=allowed, direction="long")
            for name, _ in dna["entry_genes"]:
                assert name in allowed or name in FILTER_GENES or name in ENTRY_GENES

    def test_allowed_exit_filter(self):
        allowed_exit = {"rsi_exit_high", "atr_trailing"}
        for _ in range(20):
            dna = create_strategy_dna(allowed_exit=allowed_exit, direction="long")
            exit_name = dna["exit_gene"][0]
            assert exit_name in allowed_exit

    def test_randomness_produces_variety(self):
        random.seed(None)
        dnas = [create_strategy_dna(direction="long") for _ in range(10)]
        gene_sets = [frozenset(g[0] for g in d["entry_genes"]) for d in dnas]
        # At least 2 different combinations expected over 10 runs
        assert len(set(gene_sets)) >= 2


# ─── dna_to_code() ─────────────────────────────────────────────────────────

class TestDNAToCode:
    def test_returns_string(self):
        dna = create_strategy_dna(direction="long")
        code = dna_to_code(dna)
        assert isinstance(code, str)
        assert len(code) > 0

    def test_code_is_compilable(self):
        for direction in ("long", "short", "both"):
            dna = create_strategy_dna(direction=direction)
            code = dna_to_code(dna)
            try:
                compile(code, "<dna>", "exec")
            except SyntaxError as e:
                pytest.fail(f"SyntaxError in generated code ({direction}): {e}\n{code}")

    def test_code_defines_strategy_function(self):
        dna = create_strategy_dna(direction="long")
        code = dna_to_code(dna)
        ns = {}
        exec(code, ns)
        assert "strategy" in ns
        assert callable(ns["strategy"])

    def test_strategy_function_returns_list(self):
        # Only use pure-TA genes (no derivatives that need _lookup_nearest)
        pure_ta_genes = {
            "ema_cross_up", "rsi_oversold", "bb_lower_touch", "macd_golden",
            "price_above_ema", "stoch_rsi_oversold", "donchian_breakout_up",
            "obv_rising", "vwap_above", "consecutive_bullish",
            "volume_spike", "atr_squeeze",
        }
        from backtest_engine import (
            ema, sma, rsi, bollinger_bands, atr, macd,
            obv, stoch_rsi, donchian, vwap_ratio, Candle,
        )

        closes = [100.0 + i for i in range(300)]
        candles = [Candle(i * 3600000, c * 0.999, c * 1.005, c * 0.995, c, 1000)
                   for i, c in enumerate(closes)]
        fn_ns = {
            "__builtins__": __builtins__,
            "ema": ema, "sma": sma, "rsi": rsi, "bollinger_bands": bollinger_bands,
            "atr": atr, "macd": macd, "obv": obv, "stoch_rsi": stoch_rsi,
            "donchian": donchian, "vwap_ratio": vwap_ratio,
            "_lookup_nearest": lambda d, t: None,  # stub for any derivative genes
        }

        random.seed(42)
        dna = create_strategy_dna(direction="long", allowed_entry=pure_ta_genes)
        code = dna_to_code(dna)
        exec(code, fn_ns)
        strategy_fn = fn_ns["strategy"]
        result = strategy_fn(candles, 250, {}, [])
        assert isinstance(result, list)

    def test_bidirectional_code_compilable(self):
        dna = create_strategy_dna(direction="both")
        code = dna_to_code(dna)
        compile(code, "<dna_both>", "exec")

    def test_duplicate_genes_handled(self):
        dna = create_strategy_dna(direction="long")
        # Inject duplicate gene
        first_gene = dna["entry_genes"][0]
        dna["entry_genes"].append(first_gene)
        code = dna_to_code(dna)
        compile(code, "<dup>", "exec")


# ─── mutate() ──────────────────────────────────────────────────────────────

class TestMutate:
    def test_returns_new_dna(self):
        dna = create_strategy_dna(direction="long")
        mutated = mutate(dna)
        assert mutated is not dna

    def test_original_unchanged(self):
        dna = create_strategy_dna(direction="long")
        original_genes = copy.deepcopy(dna["entry_genes"])
        mutate(dna)
        assert dna["entry_genes"] == original_genes

    def test_mutated_dna_valid(self):
        random.seed(42)
        for _ in range(30):
            dna = create_strategy_dna(direction="long")
            mutated = mutate(dna)
            dna_is_valid(mutated)

    def test_mutated_code_compilable(self):
        random.seed(0)
        for _ in range(15):
            dna = create_strategy_dna(direction="long")
            mutated = mutate(dna)
            code = dna_to_code(mutated)
            compile(code, "<mutated>", "exec")

    def test_tp_gt_sl_after_mutation(self):
        random.seed(7)
        for _ in range(30):
            dna = create_strategy_dna()
            mutated = mutate(dna)
            assert mutated["tp"] > mutated["sl"]

    def test_no_duplicate_genes_after_mutation(self):
        random.seed(99)
        for _ in range(30):
            dna = create_strategy_dna(direction="long")
            mutated = mutate(dna)
            names = [g[0] for g in mutated["entry_genes"]]
            assert len(names) == len(set(names)), f"duplicates after mutation: {names}"

    def test_max_gene_count(self):
        for _ in range(20):
            dna = create_strategy_dna(direction="long")
            mutated = mutate(dna)
            assert len(mutated["entry_genes"]) <= 4

    def test_min_gene_count(self):
        for _ in range(20):
            dna = create_strategy_dna(direction="long")
            mutated = mutate(dna)
            assert len(mutated["entry_genes"]) >= 1


# ─── crossover() ───────────────────────────────────────────────────────────

class TestCrossover:
    def test_returns_new_dna(self):
        dna1 = create_strategy_dna(direction="long")
        dna2 = create_strategy_dna(direction="long")
        child = crossover(dna1, dna2)
        assert child is not dna1
        assert child is not dna2

    def test_parents_unchanged(self):
        dna1 = create_strategy_dna(direction="long")
        dna2 = create_strategy_dna(direction="long")
        g1 = copy.deepcopy(dna1["entry_genes"])
        g2 = copy.deepcopy(dna2["entry_genes"])
        crossover(dna1, dna2)
        assert dna1["entry_genes"] == g1
        assert dna2["entry_genes"] == g2

    def test_child_valid_structure(self):
        random.seed(42)
        for _ in range(20):
            dna1 = create_strategy_dna(direction="long")
            dna2 = create_strategy_dna(direction="long")
            child = crossover(dna1, dna2)
            dna_is_valid(child)

    def test_child_genes_from_parents(self):
        random.seed(13)
        dna1 = create_strategy_dna(direction="long")
        dna2 = create_strategy_dna(direction="long")
        parent_genes = {g[0] for g in dna1["entry_genes"]} | {g[0] for g in dna2["entry_genes"]}
        child = crossover(dna1, dna2)
        for name, _ in child["entry_genes"]:
            assert name in parent_genes or name in ENTRY_GENES

    def test_child_code_compilable(self):
        random.seed(1)
        for _ in range(10):
            dna1 = create_strategy_dna(direction="long")
            dna2 = create_strategy_dna(direction="long")
            child = crossover(dna1, dna2)
            code = dna_to_code(child)
            compile(code, "<child>", "exec")

    def test_tp_gt_sl_after_crossover(self):
        random.seed(5)
        for _ in range(20):
            dna1 = create_strategy_dna()
            dna2 = create_strategy_dna()
            child = crossover(dna1, dna2)
            assert child["tp"] > child["sl"]


# ─── score_strategy() ──────────────────────────────────────────────────────

class TestScoreStrategy:
    def test_error_metrics_returns_minus_999(self):
        assert score_strategy({"error": "No trades"}) == -999
        assert score_strategy({}) == -999
        assert score_strategy(None) == -999

    def test_too_few_trades_returns_minus_999(self):
        m = good_metrics(total_trades=3)
        assert score_strategy(m) == -999

    def test_good_strategy_positive_score(self):
        m = good_metrics()
        score = score_strategy(m)
        assert score > 0

    def test_high_drawdown_penalized(self):
        m_low_dd = good_metrics(max_drawdown_pct=5.0)
        m_high_dd = good_metrics(max_drawdown_pct=40.0)
        assert score_strategy(m_low_dd) > score_strategy(m_high_dd)

    def test_higher_sharpe_higher_score(self):
        m1 = good_metrics(sharpe_ratio=0.5)
        m2 = good_metrics(sharpe_ratio=2.0)
        assert score_strategy(m2) > score_strategy(m1)

    def test_higher_roi_higher_score(self):
        m1 = good_metrics(roi_pct=5.0)
        m2 = good_metrics(roi_pct=50.0)
        assert score_strategy(m2) > score_strategy(m1)

    def test_walk_forward_bonus_for_low_overfit(self):
        m = good_metrics()
        score_no_wf = score_strategy(m)
        score_good_wf = score_strategy(m, wf_overfit=1.5)   # overfit <= 2 → bonus
        assert score_good_wf > score_no_wf

    def test_walk_forward_penalty_for_overfit(self):
        m = good_metrics()
        score_no_wf = score_strategy(m)
        score_overfit = score_strategy(m, wf_overfit=6.0)   # > 5 → slash 50%
        assert score_overfit < score_no_wf

    def test_walk_forward_extreme_overfit(self):
        m = good_metrics()
        score_extreme = score_strategy(m, wf_overfit=999)   # lost money → slash 70%
        score_normal = score_strategy(m)
        assert score_extreme < score_normal

    def test_few_trades_scale_down(self):
        m_few = good_metrics(total_trades=8)
        m_many = good_metrics(total_trades=30)
        assert score_strategy(m_many) > score_strategy(m_few)

    def test_imbalanced_long_short_penalized(self):
        m_balanced = good_metrics(long_trades=15, short_trades=15, total_trades=30)
        m_imbalanced = good_metrics(long_trades=29, short_trades=1, total_trades=30)
        assert score_strategy(m_balanced) > score_strategy(m_imbalanced)

    def test_score_is_deterministic(self):
        m = good_metrics()
        s1 = score_strategy(m)
        s2 = score_strategy(m)
        assert s1 == s2

    def test_returns_float(self):
        m = good_metrics()
        assert isinstance(score_strategy(m), float)

    def test_all_losses_low_score(self):
        m = good_metrics(win_rate=0, roi_pct=-30, profit_factor=0, sharpe_ratio=-1,
                         max_drawdown_pct=30)
        score = score_strategy(m)
        assert score < score_strategy(good_metrics())
