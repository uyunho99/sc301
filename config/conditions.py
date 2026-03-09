"""
config/conditions.py - Transition 조건 매핑

RULE_CONDITION_MAP: 레거시 fallback용 조건 ID 매핑
OR_LOGIC_RULES: OR 로직 사용 DecisionRule 집합
"""
from __future__ import annotations

# Transition별 관련 Condition ID 매핑 (레거시 fallback)
# CONSIDERS 관계가 있는 DB에서는 CONSIDERS가 우선 사용됨.
# CONSIDERS가 없는 DB (d371fecd 등)에서 fallback으로 사용.
RULE_CONDITION_MAP = {
    "ruleBodyFatHigh": ["condBmiStandard"],
    "ruleBodyFatLow": ["condBmiLowFat"],
    "ruleStandardGuide": ["condProtoclStandard"],
    "ruleLowFatGuideA": ["condProtoclLowFat", "condWeightGainIntent"],
    "ruleLowFatGuideB": ["condProtoclLowFat", "condWeightGainIntentNone"],
    "ruleRegionSemiRemote": ["condRegionSemiRemoteA", "condRegionSemiRemoteB"],
    "ruleRegionRemote": ["condRegionRemote"],
    "ruleInbodyPhotoUpload": ["condInbodyAvailable"],
    "ruleCancerNone": ["condBreastCancerNone"],
    "ruleCancerConditional": ["condBreastCancerHistory", "condCancerSurgeryTypePartial"],
    "ruleCancerNotAllowed": ["condBreastCancerHistory", "condCancerSurgeryTypeTotal"],
    "ruleImplantNone": ["condImplantNone"],
    "ruleImplantIntact": ["condImplantPresence", "condImplantConditionIntact"],
    "ruleImplantDamaged": ["condImplantPresence", "condImplantConditionDamaged"],
}

# OR 로직을 사용하는 DecisionRule (기본값은 AND)
# CONSIDERS에는 AND/OR 의미가 없으므로 별도 지정
OR_LOGIC_RULES = {
    "ruleRegionStandard",  # condRegionSeoul OR condRegionGyeonggi
}
