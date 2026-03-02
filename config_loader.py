"""
config_loader.py - YAML 설정 파싱/검증/병합

graph.yaml, knowledge.yaml, consultation_tone.yaml을 로드하여
graph_builder와 flow 엔진에서 사용할 수 있는 통합 config dict를 생성.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ConfigLoader:
    """YAML config 파일 로더/검증기."""

    def __init__(self, config_dir: str | Path) -> None:
        self.config_dir = Path(config_dir)
        self._graph: dict | None = None
        self._knowledge: dict | None = None
        self._consultation: dict | None = None

    # ------------------------------------------------------------------
    # 개별 로드
    # ------------------------------------------------------------------

    def load_graph_config(self) -> dict:
        """graph.yaml 로드."""
        if self._graph is None:
            self._graph = self._load_yaml("graph.yaml")
        return self._graph

    def load_knowledge_config(self) -> dict:
        """knowledge.yaml 로드."""
        if self._knowledge is None:
            self._knowledge = self._load_yaml("knowledge.yaml")
        return self._knowledge

    def load_consultation_config(self) -> dict:
        """consultation_tone.yaml 로드 (정규식 사전 컴파일 포함)."""
        if self._consultation is None:
            raw = self._load_yaml("consultation_tone.yaml")
            self._consultation = self._compile_consultation(raw)
        return self._consultation

    # ------------------------------------------------------------------
    # 통합 로드
    # ------------------------------------------------------------------

    def load_all(self) -> dict:
        """3개 config 병합하여 반환."""
        graph = self.load_graph_config()
        knowledge = self.load_knowledge_config()
        consultation = self.load_consultation_config()

        return {
            "version": graph.get("version", "1.0"),
            "hospital": graph.get("hospital", {}),
            "defaults": graph.get("defaults", {}),
            # graph 구조
            "personas": graph.get("personas", {}),
            "scenarios": graph.get("scenarios", {}),
            "steps": graph.get("steps", {}),
            "step_order": graph.get("step_order", {}),
            "check_items": graph.get("check_items", {}),
            "guides": graph.get("guides", {}),
            "options": graph.get("options", {}),
            # 분기/규칙
            "branching": graph.get("branching", {}),
            "rule_condition_map": graph.get("rule_condition_map", {}),
            "or_logic_rules": graph.get("or_logic_rules", []),
            "conditions": graph.get("conditions", {}),
            "decision_rules": graph.get("decision_rules", {}),
            "guide_selection": graph.get("guide_selection", {}),
            "skip_rules": graph.get("skip_rules", {}),
            "auto_compute": graph.get("auto_compute", {}),
            "lookup_tables": graph.get("lookup_tables", {}),
            # knowledge
            "surgeries": knowledge.get("surgeries", {}),
            "surgery_side_effects": knowledge.get("surgery_side_effects", {}),
            "programs": knowledge.get("programs", {}),
            "program_side_effects": knowledge.get("program_side_effects", {}),
            # consultation tone
            "consultation": consultation,
            # flow engine runtime config
            "flow_defaults": graph.get("flow_defaults", {}),
            "persona_keywords": graph.get("persona_keywords", {}),
        }

    # ------------------------------------------------------------------
    # 검증
    # ------------------------------------------------------------------

    def validate(self) -> list[str]:
        """설정 파일 검증. 에러 메시지 리스트 반환 (빈 리스트 = 정상)."""
        errors: list[str] = []
        config = self.load_all()

        # 1) 필수 파일 존재 여부
        for fname in ("graph.yaml", "knowledge.yaml", "consultation_tone.yaml"):
            fpath = self.config_dir / fname
            if not fpath.exists():
                errors.append(f"파일 없음: {fpath}")

        # 2) 시나리오 → Step 참조 무결성
        steps = config.get("steps", {})
        for scen_id, scen in config.get("scenarios", {}).items():
            for step_id in scen.get("steps", []):
                if step_id not in steps:
                    errors.append(f"시나리오 '{scen_id}'가 존재하지 않는 Step '{step_id}'를 참조")

        # 3) Step → CheckItem 참조 무결성
        check_items = config.get("check_items", {})
        for step_id, step in steps.items():
            for ci_id in step.get("checks", []):
                if ci_id not in check_items:
                    errors.append(f"Step '{step_id}'가 존재하지 않는 CheckItem '{ci_id}'를 참조")

        # 4) Step → Guide 참조 무결성
        guides = config.get("guides", {})
        for step_id, step in steps.items():
            for g_id in step.get("guides", []):
                if g_id not in guides:
                    errors.append(f"Step '{step_id}'가 존재하지 않는 Guide '{g_id}'를 참조")

        # 5) Step → Program 참조 무결성
        programs = config.get("programs", {})
        for step_id, step in steps.items():
            for p_id in step.get("programs", []):
                if p_id not in programs:
                    errors.append(f"Step '{step_id}'가 존재하지 않는 Program '{p_id}'를 참조")

        # 6) step_order 참조 무결성
        step_order = config.get("step_order", {})
        for from_id, to_val in step_order.items():
            if from_id not in steps:
                errors.append(f"step_order의 from '{from_id}'가 steps에 없음")
            targets = to_val if isinstance(to_val, list) else [to_val]
            for t in targets:
                if t not in steps:
                    errors.append(f"step_order의 to '{t}' (from '{from_id}')가 steps에 없음")

        # 7) branching rule_id → decision_rules 참조
        decision_rules = config.get("decision_rules", {})
        for step_id, rules in config.get("branching", {}).items():
            if step_id not in steps:
                errors.append(f"branching의 Step '{step_id}'가 steps에 없음")
            for rule in rules:
                rid = rule.get("rule_id")
                if rid and rid not in decision_rules:
                    errors.append(f"branching '{step_id}'의 rule_id '{rid}'가 decision_rules에 없음")

        # 8) guide_selection → guide 참조
        for step_id, sel in config.get("guide_selection", {}).items():
            for mode, guide_ids in sel.get("mapping", {}).items():
                for g_id in guide_ids:
                    if g_id not in guides:
                        errors.append(
                            f"guide_selection '{step_id}' mode '{mode}'의 Guide '{g_id}'가 guides에 없음"
                        )

        # 9) CheckItem → Option 참조
        options = config.get("options", {})
        for ci_id, ci in check_items.items():
            for opt_id in ci.get("options", []):
                if opt_id not in options:
                    errors.append(f"CheckItem '{ci_id}'가 존재하지 않는 Option '{opt_id}'를 참조")

        # 10) auto_compute → compute 함수 존재 확인
        from plugins import COMPUTE_REGISTRY, load_default_plugins

        load_default_plugins()
        for slot_id, ac in config.get("auto_compute", {}).items():
            fn_name = ac.get("compute")
            if fn_name and fn_name not in COMPUTE_REGISTRY:
                errors.append(f"auto_compute '{slot_id}'의 compute '{fn_name}'이 COMPUTE_REGISTRY에 없음")

        if errors:
            for e in errors:
                logger.error("Config validation: %s", e)
        else:
            logger.info("Config validation passed (0 errors)")

        return errors

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _load_yaml(self, filename: str) -> dict:
        """YAML 파일 로드."""
        fpath = self.config_dir / filename
        if not fpath.exists():
            raise FileNotFoundError(f"Config file not found: {fpath}")
        with open(fpath, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Config file must be a YAML mapping: {fpath}")
        logger.info("Loaded config: %s (%d top-level keys)", fpath, len(data))
        return data

    def _compile_consultation(self, raw: dict) -> dict:
        """consultation config에서 정규식 패턴 사전 컴파일."""
        result = dict(raw)

        # subject_patterns 컴파일
        compiled_patterns: dict[str, list[re.Pattern]] = {}
        for dim_id, patterns in raw.get("subject_patterns", {}).items():
            compiled_patterns[dim_id] = [re.compile(p) for p in patterns]
        result["_compiled_subject_patterns"] = compiled_patterns

        return result
