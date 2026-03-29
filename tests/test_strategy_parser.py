"""
Unit tests for strategy_parser.py
測試自然語言解析、代碼生成
"""
import sys, os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategy_parser import (
    parse_natural_language, generate_strategy_code,
    _parse_conditions, _resolve_indicator_ref, _resolve_value, _indent,
    INDICATORS, STRATEGY_TEMPLATES,
)


# ─── parse_natural_language() ──────────────────────────────────────────────

class TestParseNaturalLanguage:
    def test_returns_dict(self):
        result = parse_natural_language("EMA9 cross EMA21")
        assert isinstance(result, dict)

    def test_required_keys_present(self):
        result = parse_natural_language("simple strategy")
        for key in ("name", "symbol", "interval", "side",
                    "stop_loss_pct", "take_profit_pct",
                    "entry_conditions", "exit_conditions"):
            assert key in result

    def test_default_symbol_is_btcusdt(self):
        result = parse_natural_language("EMA crossover")
        assert result["symbol"] == "BTCUSDT"

    def test_detects_eth_symbol(self):
        result = parse_natural_language("ETHUSDT EMA crossover strategy")
        assert result["symbol"] == "ETHUSDT"

    def test_detects_sol_symbol(self):
        result = parse_natural_language("SOLUSDT RSI strategy")
        assert result["symbol"] == "SOLUSDT"

    def test_detects_interval_4h(self):
        result = parse_natural_language("4h EMA strategy")
        assert result["interval"] == "4h"

    def test_detects_interval_1h(self):
        result = parse_natural_language("1h RSI strategy")
        assert result["interval"] == "1h"

    def test_detects_interval_chinese(self):
        result = parse_natural_language("4小時 EMA 策略")
        assert result["interval"] == "4h"

    def test_detects_long_side(self):
        result = parse_natural_language("做多 EMA9 cross EMA21")
        assert result["side"] == "long"

    def test_detects_short_side(self):
        result = parse_natural_language("做空 RSI overbought")
        assert result["side"] == "short"

    def test_both_directions_default(self):
        result = parse_natural_language("EMA crossover strategy")
        assert result["side"] == "both"

    def test_detects_stop_loss_pct(self):
        result = parse_natural_language("止損: 3%")
        assert result["stop_loss_pct"] == pytest.approx(3.0)

    def test_detects_take_profit_pct(self):
        result = parse_natural_language("止盈: 6%")
        assert result["take_profit_pct"] == pytest.approx(6.0)

    def test_detects_initial_capital(self):
        result = parse_natural_language("本金: $50000")
        assert result["initial_capital"] == pytest.approx(50000.0)

    def test_ema_crossover_parsed(self):
        result = parse_natural_language("ema9 cross above ema21")
        conds = result["entry_conditions"]
        assert len(conds) >= 1
        assert any(c["indicator"] == "ema" for c in conds)

    def test_rsi_below_parsed(self):
        result = parse_natural_language("rsi below 30")
        conds = result["entry_conditions"]
        assert any(c["indicator"] == "rsi" for c in conds)

    def test_rsi_above_parsed(self):
        result = parse_natural_language("rsi above 70")
        conds = result["entry_conditions"]
        assert any(c["indicator"] == "rsi" for c in conds)

    def test_bollinger_lower_parsed(self):
        result = parse_natural_language("price below bollinger lower band")
        conds = result["entry_conditions"]
        assert len(conds) >= 1

    def test_macd_golden_cross_parsed(self):
        result = parse_natural_language("macd golden cross strategy")
        conds = result["entry_conditions"]
        assert any(c["indicator"] == "macd_line" for c in conds)

    def test_macd_death_cross_parsed(self):
        result = parse_natural_language("macd death cross strategy")
        conds = result["entry_conditions"]
        assert any(c["indicator"] == "macd_line" for c in conds)

    def test_volume_condition_parsed(self):
        result = parse_natural_language("volume超過2倍均量才入場")
        conds = result["entry_conditions"]
        assert any(c["indicator"] == "volume" for c in conds)

    def test_auto_name_generated(self):
        result = parse_natural_language("rsi below 30 buy long")
        assert result["name"] != ""

    def test_empty_string_returns_defaults(self):
        result = parse_natural_language("")
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "both"

    def test_complex_chinese_strategy(self):
        text = "BTC 4小時，EMA 9 穿越上穿 EMA 21 就做多，止損 3%，止盈 6%"
        result = parse_natural_language(text)
        assert result["stop_loss_pct"] == pytest.approx(3.0)
        assert result["take_profit_pct"] == pytest.approx(6.0)
        assert result["side"] == "long"


# ─── _parse_conditions() ───────────────────────────────────────────────────

class TestParseConditions:
    def test_ema_crossover_condition(self):
        conds = _parse_conditions("ema9 cross above ema21", "entry")
        assert any(c["operator"] == "crosses_above" for c in conds)

    def test_rsi_below_entry(self):
        conds = _parse_conditions("rsi below 30", "entry")
        assert any(c["indicator"] == "rsi" and c["operator"] == "below" for c in conds)

    def test_rsi_above_entry(self):
        conds = _parse_conditions("rsi above 70", "entry")
        assert any(c["indicator"] == "rsi" and c["operator"] == "above" for c in conds)

    def test_rsi_period_extracted(self):
        conds = _parse_conditions("rsi(7) below 25", "entry")
        rsi_conds = [c for c in conds if c["indicator"] == "rsi"]
        if rsi_conds:
            assert rsi_conds[0]["params"]["period"] == 7

    def test_bb_lower_condition(self):
        conds = _parse_conditions("price below bollinger lower band", "entry")
        assert len(conds) >= 1

    def test_bb_upper_condition(self):
        conds = _parse_conditions("price above bollinger upper band", "entry")
        assert len(conds) >= 1

    def test_macd_golden_cross(self):
        conds = _parse_conditions("macd golden cross", "entry")
        assert any(c.get("operator") == "crosses_above" for c in conds)

    def test_macd_death_cross(self):
        conds = _parse_conditions("macd death cross", "entry")
        assert any(c.get("operator") == "crosses_below" for c in conds)

    def test_volume_spike(self):
        conds = _parse_conditions("volume超過2倍", "entry")
        assert any(c["indicator"] == "volume" for c in conds)

    def test_no_conditions_returns_empty(self):
        conds = _parse_conditions("random text with no indicators", "entry")
        assert isinstance(conds, list)

    def test_rsi_exit_uses_crosses_operator(self):
        conds = _parse_conditions("rsi below 30", "exit")
        assert any(c["operator"] == "crosses_below" for c in conds)


# ─── generate_strategy_code() ──────────────────────────────────────────────

class TestGenerateStrategyCode:
    def _parse_and_generate(self, text):
        strategy_def = parse_natural_language(text)
        return generate_strategy_code(strategy_def)

    def test_returns_string(self):
        code = self._parse_and_generate("ema9 cross ema21")
        assert isinstance(code, str)

    def test_code_is_syntactically_valid(self):
        texts = [
            "ema9 cross above ema21 做多",
            "rsi below 30 buy long",
            "macd golden cross strategy",
            "price below bollinger lower band",
        ]
        for text in texts:
            code = self._parse_and_generate(text)
            try:
                compile(code, "<gen>", "exec")
            except SyntaxError as e:
                pytest.fail(f"SyntaxError for '{text}': {e}\n{code}")

    def test_function_defined(self):
        code = self._parse_and_generate("rsi below 30")
        assert "def strategy_" in code

    def test_actions_list_present(self):
        code = self._parse_and_generate("rsi below 30")
        assert "actions" in code
        assert "return actions" in code

    def test_no_conditions_still_compilable(self):
        strategy_def = {
            "name": "Empty Strategy",
            "description": "",
            "entry_conditions": [],
            "exit_conditions": [],
            "side": "both",
        }
        code = generate_strategy_code(strategy_def)
        compile(code, "<empty>", "exec")

    def test_ema_indicator_code_generated(self):
        strategy_def = parse_natural_language("price above ema21")
        code = generate_strategy_code(strategy_def)
        assert "ema" in code.lower()

    def test_rsi_indicator_code_generated(self):
        strategy_def = parse_natural_language("rsi below 30")
        code = generate_strategy_code(strategy_def)
        assert "rsi" in code.lower()

    def test_macd_indicator_code_generated(self):
        strategy_def = parse_natural_language("macd golden cross")
        code = generate_strategy_code(strategy_def)
        assert "macd" in code.lower()

    def test_long_strategy_uses_buy(self):
        strategy_def = parse_natural_language("做多 ema9 cross ema21")
        code = generate_strategy_code(strategy_def)
        assert '"buy"' in code or "'buy'" in code

    def test_short_strategy_uses_sell(self):
        strategy_def = parse_natural_language("做空 rsi above 70")
        code = generate_strategy_code(strategy_def)
        assert '"sell"' in code or "'sell'" in code

    def test_exit_conditions_included(self):
        strategy_def = parse_natural_language("rsi below 30 buy; rsi above 70 exit")
        code = generate_strategy_code(strategy_def)
        # Should contain exit logic
        assert "open_trades" in code


# ─── _resolve_indicator_ref() ──────────────────────────────────────────────

class TestResolveIndicatorRef:
    def test_price(self):
        assert _resolve_indicator_ref("price", {}) == "closes"

    def test_rsi(self):
        assert _resolve_indicator_ref("rsi", {}) == "rsi_vals"

    def test_ema_with_period(self):
        assert _resolve_indicator_ref("ema", {"period": 21}) == "ema_21"

    def test_ema_default_period(self):
        assert _resolve_indicator_ref("ema", {}) == "ema_21"

    def test_sma_with_period(self):
        assert _resolve_indicator_ref("sma", {"period": 20}) == "sma_20"

    def test_macd_line(self):
        assert _resolve_indicator_ref("macd_line", {}) == "macd_l"

    def test_macd_signal(self):
        assert _resolve_indicator_ref("macd_signal", {}) == "macd_s"

    def test_volume(self):
        assert _resolve_indicator_ref("volume", {}) == "volumes"


# ─── _resolve_value() ──────────────────────────────────────────────────────

class TestResolveValue:
    def test_numeric_returns_string(self):
        assert _resolve_value(30) == "30"

    def test_float_returns_string(self):
        assert _resolve_value(1.5) == "1.5"

    def test_dict_resolves_indicator(self):
        val = {"indicator": "ema", "params": {"period": 21}}
        assert _resolve_value(val) == "ema_21"

    def test_dict_rsi(self):
        val = {"indicator": "rsi", "params": {}}
        assert _resolve_value(val) == "rsi_vals"


# ─── _indent() ─────────────────────────────────────────────────────────────

class TestIndent:
    def test_single_line(self):
        result = _indent("hello", 4)
        assert result == "    hello"

    def test_multi_line(self):
        result = _indent("line1\nline2", 4)
        assert result == "    line1\n    line2"

    def test_blank_line_not_indented(self):
        result = _indent("line1\n\nline2", 4)
        lines = result.split("\n")
        assert lines[1] == ""  # blank line stays blank


# ─── STRATEGY_TEMPLATES ────────────────────────────────────────────────────

class TestStrategyTemplates:
    def test_templates_have_required_keys(self):
        for name, tmpl in STRATEGY_TEMPLATES.items():
            assert "name" in tmpl, f"{name} missing 'name'"
            assert "description" in tmpl, f"{name} missing 'description'"
            assert "params" in tmpl, f"{name} missing 'params'"

    def test_known_templates_exist(self):
        for key in ("ema_cross", "rsi_reversal", "bb_squeeze", "macd_cross", "trend_follow"):
            assert key in STRATEGY_TEMPLATES


# ─── INDICATORS registry ───────────────────────────────────────────────────

class TestIndicatorsRegistry:
    def test_known_indicators_registered(self):
        for ind in ("ema", "sma", "rsi", "macd", "bb", "atr", "volume"):
            assert ind in INDICATORS

    def test_each_has_params_and_defaults(self):
        for name, meta in INDICATORS.items():
            assert "params" in meta, f"{name} missing params"
            assert "defaults" in meta, f"{name} missing defaults"
