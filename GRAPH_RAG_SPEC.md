# SC301 Graph RAG 시스템 명세서

> 가슴성형(줄기세포 지방이식, 보형물 등) 전문 상담 챗봇을 위한 Neo4j 기반 Graph RAG 구조 명세
> 최종 갱신: 2026-02-21

---

## 목차

1. [전체 아키텍처 개요](#1-전체-아키텍처-개요)
2. [그래프 노드 타입 및 관계](#2-그래프-노드-타입-및-관계)
3. [페르소나별 상세 명세](#3-페르소나별-상세-명세)
   - [P1 slimBody (마른 체형)](#p1-slimbody-마른-체형)
   - [P2 lipoCustomer (지방흡입 고객)](#p2-lipocustomer-지방흡입-고객)
   - [P3 skinTreatment (피부시술)](#p3-skintreatment-피부시술)
   - [P4 longDistance (원거리)](#p4-longdistance-원거리)
   - [P5 revisionFatigue (재수술)](#p5-revisionfatigue-재수술)
4. [슬롯(Slot) 전체 목록 및 힌트](#4-슬롯slot-전체-목록-및-힌트)
5. [분기 규칙 (Branching Rules)](#5-분기-규칙-branching-rules)
6. [가이드 선택 규칙 (Guide Selection)](#6-가이드-선택-규칙-guide-selection)
7. [자동 계산 및 조건부 스킵](#7-자동-계산-및-조건부-스킵)
8. [프로그램 및 부작용](#8-프로그램-및-부작용)
9. [그래프 통계 요약](#9-그래프-통계-요약)

---

## 1. 전체 아키텍처 개요

```
┌─────────────────────────────────────────────────────┐
│                    Neo4j Graph DB                    │
│                                                     │
│  Persona ──HAS_SCENARIO──▶ Scenario                 │
│                              │                      │
│                          HAS_STEP                   │
│                              ▼                      │
│                            Step ──TO──▶ Step (순차)  │
│                           / | \                     │
│                 CHECKS  GUIDED_BY  RECOMMENDS       │
│                  ▼          ▼          ▼             │
│              CheckItem    Guide     Program         │
│                 │                      │             │
│             HAS_OPTION          HAS_SIDE_EFFECT     │
│                 ▼                      ▼             │
│              Option              SideEffect         │
│                                                     │
│  Transition ──GUARDED_BY──▶ DecisionRule            │
│                                 │                   │
│                             CONSIDERS               │
│                                 ▼                   │
│                             Condition               │
└─────────────────────────────────────────────────────┘
```

**기술 스택**: Neo4j + OpenAI (gpt-4o) + Python
**임베딩 모델**: text-embedding-3-small (1536차원, cosine)
**벡터 인덱스**: Surgery, Step, CheckItem

---

## 2. 그래프 노드 타입 및 관계

### 노드 타입

| 노드 타입 | 수량 | 설명 |
|-----------|------|------|
| **Persona** | 7 | 고객 유형 (5 메인 + 2 레거시) |
| **Scenario** | 7 | 페르소나별 상담 시나리오 |
| **Step** | 35 | 상담 단계 (collect/ask/inform/confirm/finalize) |
| **CheckItem** | 78 | 수집할 정보 항목 (슬롯) |
| **Guide** | 44 | 단계별 안내 텍스트 (protocolMode별 분기) |
| **Program** | 7 | 추천 시술 프로그램 |
| **Option** | 9 | CheckItem의 선택지 |
| **DecisionRule** | 21 | 분기 판단 규칙 |
| **Condition** | 24 | 분기 조건 (input/op/ref) |
| **ConditionGroup** | 2 | 조건 그룹 (레거시) |
| **Transition** | 16 | 스텝 간 전이 |
| **Surgery** | 6 | 수술 유형 (벡터 검색용) |
| **SideEffect** | 18 | 부작용 항목 |

### 관계 타입

| 관계 | 수량 | 방향 | 설명 |
|------|------|------|------|
| `HAS_SCENARIO` | 7 | Persona → Scenario | 페르소나별 시나리오 |
| `HAS_STEP` | 35 | Scenario → Step | 시나리오의 스텝 목록 |
| `TO` | 31 | Step → Step | 순차 진행 (1:N 분기 가능) |
| `CHECKS` | 123 | Step → CheckItem | 스텝에서 수집할 항목 |
| `ASKS_FOR` | 114 | Scenario → CheckItem | 시나리오 전체 수집 항목 |
| `GUIDED_BY` | 44 | Step → Guide | 스텝별 안내 가이드 |
| `RECOMMENDS` | 6 | Step → Program | 스텝별 추천 프로그램 |
| `HAS_OPTION` | 9 | CheckItem → Option | 선택지 |
| `HAS_SIDE_EFFECT` | 29 | Program → SideEffect | 부작용 정보 |
| `GUARDED_BY` | 19 | Transition → DecisionRule | 전이 조건 |
| `CONSIDERS` | 28 | DecisionRule → Condition | 규칙의 판단 조건 |
| `causeSideEffect` | 13 | Surgery → SideEffect | 수술별 부작용 |

---

## 3. 페르소나별 상세 명세

---

### P1 slimBody (마른 체형)

> 체지방률이 낮아 가슴 줄기세포 지방이식 시 채취 가능량이 제한될 수 있는 여성 고객. 가슴 볼륨업을 원하지만 체지방 부족으로 시술 가능 여부와 기대 결과에 대한 불확실성이 높아 사전 검진을 통한 기준 충족 여부 확인과 체중 증량 또는 대안 루트 제시를 포함한 단계적 상담을 선호함.

**시나리오**: `scenLowFat`
**추천 프로그램**: `lowFatCustromProgram`
**분기 조건**: BMI 기반 (`bmi >= 23` → STANDARD / `bmi < 23` → LOW-FAT)

#### 스텝 플로우

```
p1CollectInfo [collect]
    ↓
p1AskLifestyle [ask]
    ↓
p1AskDetail [ask]
    ↓
p1InformSurgery [inform]  ← BMI 분기 (Guide 선택)
    ↓
p1InformInfo [inform]
    ↓
p1Confirm [confirm]  → END
```

#### 스텝별 CheckItem (슬롯)

| Step | Slot ID | 설명 | 입력 힌트 |
|------|---------|------|-----------|
| **p1CollectInfo** | `bodyInfo` | 키/체중 | `170cm 65kg` |
| | `bodyFat` | 체지방률 | `25%` |
| | `bodyType` | 체형 분류 | 마른편 / 보통 / 비만형 |
| | `inbodyAvailable` | 인바디 보유 | true / false |
| **p1AskLifestyle** | `activityPattern` | 활동 패턴 | 사무직, 활동적, 운동 자주 |
| | `exerciseLevel` | 운동 빈도 | 주 3회, 거의 안 함 |
| | `dietPattern` | 식습관 | 저탄고지, 불규칙 |
| | `weightGainIntent` | 증량 의사 | true / false |
| **p1AskDetail** | `fatSourceAvailability` | 지방 채취 가능 | 복부 충분, 허벅지 소량 |
| | `pastOps` | 과거 수술 이력 | 가슴 확대 1회, 없음 |
| | `pastOpsSite` | 과거 수술 부위 | 복부, 허벅지, 가슴 |
| **p1InformSurgery** | *(정보 제공 단계 - 수집 없음)* | | |
| **p1InformInfo** | `nutritionConsult` | 영양 상담 희망 | true / false |
| | `recoveryGuideline` | 회복 가이드라인 | 2주간 압박복, 음주 금지 |
| | `weightGainPlan` | 증량 계획 | (자유 텍스트) |
| **p1Confirm** | `customerName` | 고객 성함 | (이름) |
| | `phoneNumber` | 연락처 | 010-1234-5678 |
| | `recheckSchedule` | 재진 일정 | 2주 후 |
| | `surgeryWindow` | 희망 시술 시기 | 다음 달, 3개월 내 |

**자동 계산 슬롯**: `bmi` (bodyInfo에서 키/체중 추출 → BMI 자동 산출)
**조건부 스킵**: `weightGainPlan`, `nutritionConsult` (weightGainIntent=false일 때 스킵)
**시스템 관리 슬롯**: `protocolMode` (STANDARD / LOW-FAT)

#### 가이드 매핑

| Step | Guide | 조건 |
|------|-------|------|
| p1InformSurgery | `guideGraftInfoStandard` | protocolMode = STANDARD |
| p1InformSurgery | `guideGraftInfoLowFat` | protocolMode = LOW-FAT |
| p1InformInfo | `guideGraftTimelineStandard` | protocolMode = STANDARD |
| p1InformInfo | `guideGraftTimelineLowFatIntent` | protocolMode = LOW-FAT + weightGainIntent=true |
| p1Confirm | `guideBookingDiscount` | (기본) |
| p1Confirm | `guideGraftScheduleLowFat` | (기본) |

---

### P2 lipoCustomer (지방흡입 고객)

> 지방흡입 후 가슴에 이식(특히 줄기세포 지방이식)에 관심이 있는 여성 고객. 효과 발현 시점/부작용 위험/비용 대비 만족도를 핵심 기준으로 판단함. 일반 지방이식 vs 줄기세포 지방이식 등 시술 방식 간 차이를 명확히 비교해줄 때 신뢰가 생기며, 정보 탐색을 충분히 하되 빠른 예약으로 직접 상담을 받기를 원함.

**시나리오**: `scenLipoGraft`
**추천 프로그램**: `lipoStandalone` (흡입 단독) / `lipoGraftCombined` (흡입+이식) / `stemCellGraft` (줄기세포)
**분기 조건**: 2단계 분기
1. `upsellAccept` → 흡입 단독(A) vs 흡입+이식(B)
2. `transferType` → 일반 vs 줄기세포 (B 경로에서만)

#### 스텝 플로우

```
p2PreCollect [collect]
    ↓
p2Collect [collect]
    ↓
p2AskLifestyle [ask]
    ↓
p2AskDetail [ask]
    ↓
p2InformSurgery [inform]  ← upsellAccept 분기
    ├── (upsellAccept=false) → p2InformInfoA [inform]  → p2Finalize
    └── (upsellAccept=true)  → p2InformInfoB [inform]  ← transferType 분기
                                                            → p2Finalize [finalize] → END
```

#### 스텝별 CheckItem (슬롯)

| Step | Slot ID | 설명 | 입력 힌트 |
|------|---------|------|-----------|
| **p2PreCollect** | `basicInfo` | 이름/연락처 | 김지현 010-1234-5678 |
| | `bodyInfo` | 키/체중 | 170cm 65kg |
| | `concernArea` | 관심 부위 | 가슴 볼륨, 가슴 탄력 |
| | `medicalHistory` | 과거 병력 | (자유 텍스트) |
| | `schedule` | 방문 가능 일정 | (자유 텍스트) |
| **p2Collect** | `bodyInfo` | 키/체중 | 170cm 65kg |
| | `schedule` | 방문 가능 일정 | (자유 텍스트) |
| | `travelConstraint` | 이동 제약 | (자유 텍스트) |
| **p2AskLifestyle** | `activityPattern` | 활동 패턴 | 사무직, 활동적 |
| | `exerciseLevel` | 운동 빈도 | 주 3회, 거의 안 함 |
| | `jobIntensity` | 직업 강도 | 사무직(낮음), 현장직(높음) |
| | `recoveryAllowance` | 회복 가능 기간 | 1주일, 2주 |
| | `smoking` | 흡연 여부 | true / false |
| **p2AskDetail** | `fatSourceAvailability` | 지방 채취 가능 | 복부 충분 |
| | `lipoArea` | 흡입 희망 부위 | 복부, 허벅지 |
| | `lipoGoal` | 흡입 목표 | 가슴 볼륨업, 가슴 지방이식용 채취 |
| | `pastOps` | 과거 수술 이력 | (자유 텍스트) |
| | `riskFactor` | 위험 요소 | 고혈압, 당뇨, 없음 |
| **p2InformSurgery** | `upsellAccept` | 이식 추가 동의 | true / false |
| | `costSensitivity` | 비용 민감도 | 예산 중요, 결과 우선 |
| | `planPreference` | 계획 선호 | 한 번에, 단계별 |
| | `concernSideEffect` | 우려 부작용 | 울퉁불퉁, 비대칭 |
| | `recoveryAllowance` | 회복 가능 기간 | 1주일, 2주 |
| **p2InformInfoA** | `lipoPlanDetail` | 흡입 세부 계획 | 복부+옆구리 동시 |
| (흡입 단독) | `recoveryTimeline` | 회복 일정 | 1주 후 출근 |
| | `costRange` | 예산 범위 | 300만원 이내 |
| **p2InformInfoB** | `transferType` | 이식 유형 | 일반 / 줄기세포 |
| (흡입+이식) | `transferPlanDetail` | 이식 세부 계획 | 줄기세포 이식 + 가슴 볼륨 보충 |
| | `graftExpectation` | 이식 기대 효과 | 자연스러운 가슴 볼륨 |
| | `recoveryTimeline` | 회복 일정 | 2주 재택 |
| | `costRange` | 예산 범위 | 500만원 이내 |
| **p2Finalize** | `reservationIntent` | 예약 의사 | true / false |
| | `visitSchedule` | 방문 예약 일정 | (날짜) |
| | `precheckRequired` | 사전검사 필요 | true / false |
| | `sameDayPossible` | 당일 시술 가능 | true / false |

#### 가이드 매핑

| Step | Guide | 조건 |
|------|-------|------|
| p2InformSurgery | `guideCompareLipoOnly` | (기본 비교 안내) |
| p2InformSurgery | `guideCompareLipoPlusTransfer` | (이식 포함 비교) |
| p2InformInfoA | `guideRecommendLipoOnly` | 흡입 단독 추천 |
| p2InformInfoB | `guideRecommendLipoPlusGeneral` | 흡입+이식 추천 |
| p2Finalize | `guideTriggerLipoOnly` | 흡입 단독 마무리 |
| p2Finalize | `guideTriggerLipoPlusTransfer` | 흡입+이식 마무리 |

#### transferPlanDetail 옵션

| Option | Value |
|--------|-------|
| simultaneous | 동시 진행 |
| staged | 단계별 진행 |
| undecided | 미정 |

---

### P3 skinTreatment (피부시술)

> 가슴성형 전후 피부관리를 목적으로 시술을 고려하는 고객. 가슴 수술 후 피부 탄력 회복, 흉터 관리 등을 중시하며, 과거 시술 경험이 있는 경우도 많아 기존 시술과의 관계에 민감함. 복잡한 의학 설명보다는 쉽고 직관적인 비교 설명을 선호함.

**시나리오**: `scenAntiAging`
**추천 프로그램**: `faceAntiAgingProgram`
**분기 조건**: 없음 (선형 플로우)

#### 스텝 플로우

```
p3Collect [collect]
    ↓
p3AskLifestyle [ask]
    ↓
p3AskDetail [ask]
    ↓
p3AskSurgery [ask]
    ↓
p3InformSugery [inform]
    ↓
p3Confirm [confirm]  → END
```

#### 스텝별 CheckItem (슬롯)

| Step | Slot ID | 설명 | 입력 힌트 |
|------|---------|------|-----------|
| **p3Collect** | `bodyInfo` | 키/체중 | 170cm 65kg |
| | `bodyFat` | 체지방률 | 25% |
| | `skinType` | 피부 타입 | 건성, 지성, 복합성, 민감성 |
| | `skinCondition` | 피부 상태 | 가슴 부위 탄력 저하, 수술 후 흉터 |
| **p3AskLifestyle** | `activityPattern` | 활동 패턴 | 사무직, 활동적 |
| | `skincareRoutine` | 스킨케어 루틴 | 기초만, 풀코스, 거의 안 함 |
| | `smoking` | 흡연 여부 | true / false |
| | `sunExposure` | 자외선 노출 | 야외 많음, 실내 위주 |
| **p3AskDetail** | `allergyHistory` | 알레르기 이력 | (자유 텍스트) |
| | `botoxCycle` | 보톡스 주기 | 6개월마다, 처음 |
| | `fatSourceAvailability` | 지방 채취 가능 | 복부 충분 |
| | `fillerRemaining` | 필러 잔여량 | 거의 흡수됨, 일부 남음 |
| | `pastOps` | 과거 수술 이력 | (자유 텍스트) |
| | `pastOpsSite` | 과거 수술 부위 | (자유 텍스트) |
| **p3AskSurgery** | `concernArea` | 관심 부위 | 가슴 부위 수술 전후 피부 |
| | `desiredEffect` | 희망 효과 | 수술 후 피부 탄력 회복, 흉터 최소화 |
| | `durabilityExpectation` | 지속 기간 기대 | 6개월 이상, 1년, 반영구 |
| **p3InformSugery** | *(정보 제공 단계)* | | |
| **p3Confirm** | `customerName` | 고객 성함 | (이름) |
| | `phoneNumber` | 연락처 | 010-1234-5678 |
| | `procedurePlan` | 시술 계획 | (자유 텍스트) |
| | `surgeryWindow` | 희망 시기 | 다음 달, 3개월 내 |
| | `visitSchedule` | 방문 일정 | (날짜) |

---

### P4 longDistance (원거리)

> 해외 또는 국내 원거리 거주로 병원 방문이 제한적인 여성 고객. 가슴 줄기세포 지방이식을 위해 상담-검사-시술-사후관리까지 일정 효율 최적화를 최우선으로 고려함. 체류 기간을 빠르게 확정하고, 원격 환자 프로토콜(Remote Patient Protocol)을 통해 국내 고객과 동등한 생착률을 보장받는 맞춤 프로그램을 원함.

**시나리오**: `scenRemote`
**추천 프로그램**: `longDistanceProgram`
**분기 조건**: 거주지 기반 3-way 프로토콜

#### 프로토콜 분기

| 조건 | protocolMode | 설명 |
|------|-------------|------|
| `residenceCountry = ABROAD` | **FULL** | 해외 거주 (전면 원격) |
| `regionBucket != S1 && != S2` | **SEMI-REMOTE** | 국내 원거리 (S3~S6) |
| `regionBucket = S1 또는 S2` | **STANDARD** | 수도권 (서울/경기) |

#### 지역 분류 (regionBucket)

| 코드 | 지역 |
|------|------|
| S1 | 서울 |
| S2 | 경기, 인천 |
| S3 | 대전, 세종, 충남, 충북 |
| S4 | 부산, 대구, 울산, 경남, 경북 |
| S5 | 광주, 전남, 전북 |
| S6 | 강원, 제주 |
| ABROAD | 해외 |

#### 스텝 플로우

```
p4PreCollect [collect]  ← regionBucket 분기 (protocolMode 결정)
    ↓
p4Collect [collect]
    ↓
p4AskLifestyle [ask]
    ↓
p4AskDetail [ask]
    ↓
p4InformSurgery [inform]
    ↓
p4InformInfo [inform]
    ↓
p4Confirm [confirm]
    ↓
p4Finalize [finalize]  → END
```

#### 스텝별 CheckItem (슬롯)

| Step | Slot ID | 설명 | 입력 힌트 |
|------|---------|------|-----------|
| **p4PreCollect** | `residenceCountry` | 거주국 | 한국, 미국, 일본, 해외 |
| | `domesticDistrict` | 국내 지역 | 서울, 부산, 경기 |
| | `regionBucket` | 지역 코드 | **자동 계산** (S1~S6/ABROAD) |
| | `travelConstraint` | 이동 제약 | (자유 텍스트) |
| | `visitPeriod` | 방문/체류 기간 | (자유 텍스트) |
| **p4Collect** | `bodyInfo` | 키/체중 | 170cm 65kg |
| | `bodyFat` | 체지방률 | 25% |
| | `inbodyAvailable` | 인바디 보유 | true / false |
| | `inbodyPhotoUpload` | 인바디 사진 업로드 | true / false |
| **p4AskLifestyle** | `activityPattern` | 활동 패턴 | 사무직, 활동적 |
| | `exerciseLevel` | 운동 빈도 | 주 3회, 거의 안 함 |
| | `recoveryAllowance` | 회복 가능 기간 | 1주일, 2주 |
| | `smoking` | 흡연 여부 | true / false |
| **p4AskDetail** | `fatSourceAvailability` | 지방 채취 가능 | 복부 충분 |
| | `pastOps` | 과거 수술 이력 | (자유 텍스트) |
| | `pastOpsSite` | 과거 수술 부위 | (자유 텍스트) |
| **p4InformSurgery** | *(정보 제공 단계)* | | |
| **p4InformInfo** | `bodyPhotoUpload` | 체형 사진 업로드 | true / false |
| | `documentUpload` | 서류 업로드 | true / false |
| | `precheckTimeEstimate` | 사전검사 소요시간 | 30분, 1시간 |
| **p4Confirm** | `depositReservation` | 예약금 결제 | true / false |
| | `surgeryWindow` | 희망 시기 | 다음 달, 3개월 내 |
| **p4Finalize** | `aftercarePlan` | 사후 관리 계획 | (자유 텍스트) |
| | `customerName` | 고객 성함 | (이름) |
| | `followupSchedule` | 사후관리 일정 | (날짜) |
| | `phoneNumber` | 연락처 | 010-1234-5678 |

**자동 계산**: `regionBucket` (residenceCountry + domesticDistrict → 자동 매핑)
**조건부 스킵**: `domesticDistrict` (residenceCountry=ABROAD일 때), `inbodyPhotoUpload` (inbodyAvailable=false일 때)

#### 가이드 매핑 (protocolMode별)

| Step | STANDARD | SEMI-REMOTE | FULL (해외) |
|------|----------|-------------|-------------|
| p4PreCollect | `guideStandardPremise` | `guideSemiremotePremise` | `guideAbroadPremise` |
| p4Collect | `guideStandardInbody` | `guideSemiremoteInbody` | `guideAbroadInbody` |
| p4AskLifestyle | `guideStandardRecovery` | `guideSemiremoteLogic` | `guideAbroadLogic` |
| p4AskDetail | *(없음)* | `guideSemiremoteProcess` | `guideAbroadProcess` |
| p4InformSurgery | `guideStandardProcess` | `guideSemiremoteRoute` | `guideAbroadProtocol` |
| p4InformInfo | `guideStandardUpload` | `guideSemiremoteUpload` | `guideAbroadUpload` |
| p4Confirm | `guideStandardBooking` | `guideSemiremoteBooking` | `guideAbroadBooking` |
| p4Finalize | `guideStandardPostCare` | `guideSemiremotePostCare` | `guideAbroadPostCare` |

---

### P5 revisionFatigue (재수술)

> 과거 가슴 수술 이후 이물감, 비대칭, 자연스러움 부족 등의 경험으로 재수술을 고민하는 여성 고객. 반복된 시술로 심리적 피로와 불안이 큼. 자연스러운 가슴 형태 및 촉감을 선호하며, 석회화/괴사/흉터와 같은 리스크에 매우 민감함. 가능하다면 한 번에 끝나는 안정적인 원스텝 플랜을 선호함.

**시나리오**: `scenRevision`
**추천 프로그램**: `revisionGraftProgram`
**분기 조건**: 유방암 병력 + 보형물 상태 기반 복합 분기

#### 분기 로직 (p5AskMedical)

```
breastCancerHistory?
├── false → STANDARD (ruleCancerNone)
├── true + cancerSurgeryType=부분 → CONDITIONAL (ruleCancerConditional)
└── true + cancerSurgeryType=완전 → NOT_ALLOWED (ruleCancerNotAllowed)

implantPresence?
├── false → guideImplantNone
├── true + implantCondition=온전 → guideImplantIntact / guideImplantInhouse
└── true + implantCondition=손상 → guideImplantDamaged / guideImplantExternal
```

#### 스텝 플로우

```
p5Collect [collect]
    ↓
p5AskLifestyle [ask]
    ↓
p5AskDetail [ask]
    ↓
p5AskMedical [ask]  ← 유방암/보형물 분기
    ↓
p5InformSurgery [inform]
    ↓
p5InformInfo [inform]
    ↓
p5Confirm [confirm]  → END
```

#### 스텝별 CheckItem (슬롯)

| Step | Slot ID | 설명 | 입력 힌트 |
|------|---------|------|-----------|
| **p5Collect** | `bodyInfo` | 키/체중 | 170cm 65kg |
| | `bodyFat` | 체지방률 | 25% |
| | `bodyType` | 체형 분류 | 마른편 / 보통 / 비만형 |
| **p5AskLifestyle** | `activityPattern` | 활동 패턴 | 사무직, 활동적 |
| | `recoveryAllowance` | 회복 가능 기간 | 1주일, 2주 |
| | `smoking` | 흡연 여부 | true / false |
| | `workConstraint` | 직업 제약 | 2주 후 출근 필수, 재택 가능 |
| **p5AskDetail** | `breastCancerHistory` | 유방암 병력 | true / false |
| | `cancerSurgeryType` | 암 수술 유형 | 부분절제 / 전절제 |
| | `fatSourceAvailability` | 지방 채취 가능 | 복부 충분 |
| | `implantPresence` | 보형물 존재 | true / false |
| | `pastOps` | 과거 수술 이력 | (자유 텍스트) |
| | `pastOpsSite` | 과거 수술 부위 | (자유 텍스트) |
| **p5AskMedical** | `implantCondition` | 보형물 상태 | 양호, 파손, 구축 |
| | `implantOriginHospital` | 시술 병원명 | (자유 텍스트) |
| **p5InformSurgery** | *(정보 제공 단계)* | | |
| **p5InformInfo** | `aftercarePlan` | 사후 관리 계획 | (자유 텍스트) |
| | `riskExplanationLevel` | 위험성 설명 수준 | 상세히, 핵심만, 서면으로 |
| | `scarManagement` | 흉터 관리 | 실리콘 시트, 레이저, 자연 치유 |
| **p5Confirm** | `customerName` | 고객 성함 | (이름) |
| | `phoneNumber` | 연락처 | 010-1234-5678 |
| | `procedurePlan` | 시술 계획 | (자유 텍스트) |
| | `surgeryWindow` | 희망 시기 | 다음 달, 3개월 내 |
| | `visitSchedule` | 방문 일정 | (날짜) |

**조건부 스킵**: `implantCondition`, `implantOriginHospital` (implantPresence=false일 때)

#### 가이드 매핑

| Step | Guide | 조건 |
|------|-------|------|
| p5InformSurgery | `guideCancerNone` | breastCancerHistory = false |
| p5InformSurgery | `guideCancerPartial` | breastCancerHistory=true + cancerSurgeryType=부분 |
| p5InformSurgery | `guideCancerTotal` | breastCancerHistory=true + cancerSurgeryType=완전 |
| p5InformSurgery | `guideImplantNone` | implantPresence = false |
| p5InformSurgery | `guideImplantInhouse` | implantPresence=true + implantCondition=온전 |
| p5InformSurgery | `guideImplantExternal` | implantPresence=true + implantCondition=손상 |
| p5InformSurgery | `guideRevisionEffect` | (공통 효과 안내) |
| p5InformInfo | `guideImplantTimeline` | (공통 타임라인) |
| p5Confirm | `guideBookingEvent` | (예약 안내) |

---

## 4. 슬롯(Slot) 전체 목록 및 힌트

### 공통 신체정보

| Slot | 설명 | 입력 힌트 | 사용 페르소나 |
|------|------|-----------|-------------|
| `bodyInfo` | 키/체중 | `170cm 65kg` | P1, P2, P3, P4, P5 |
| `bodyFat` | 체지방률 | `25%` | P1, P3, P4, P5 |
| `bodyType` | 체형 분류 | 마른편/보통/비만형 | P1, P5 |
| `inbodyAvailable` | 인바디 보유 여부 | true/false | P1, P4 |
| `inbodyPhotoUpload` | 인바디 사진 업로드 | true/false | P4 |

### 공통 시술 이력

| Slot | 설명 | 입력 힌트 | 사용 페르소나 |
|------|------|-----------|-------------|
| `fatSourceAvailability` | 지방 채취 가능 부위/량 | 복부 충분, 허벅지 소량 | P1, P2, P3, P4, P5 |
| `pastOps` | 과거 수술 이력 | 가슴 확대 1회, 없음 | P1, P2, P3, P4, P5 |
| `pastOpsSite` | 과거 수술 부위 | 가슴, 가슴 좌측, 가슴 양측 | P1, P3, P4, P5 |
| `smoking` | 흡연 여부 | true/false | P2, P3, P4, P5 |

### 공통 생활습관

| Slot | 설명 | 입력 힌트 | 사용 페르소나 |
|------|------|-----------|-------------|
| `activityPattern` | 일상 활동 패턴 | 사무직, 활동적 | P1, P2, P3, P4, P5 |
| `exerciseLevel` | 운동 빈도/강도 | 주 3회, 거의 안 함 | P1, P2, P4 |
| `recoveryAllowance` | 회복 가능 기간 | 1주일, 2주 | P2, P4, P5 |

### 공통 마무리

| Slot | 설명 | 입력 힌트 | 사용 페르소나 |
|------|------|-----------|-------------|
| `customerName` | 고객 성함 | (이름) | P1, P3, P4, P5 |
| `phoneNumber` | 연락처 | 010-1234-5678 | P1, P3, P4, P5 |
| `surgeryWindow` | 희망 시술 시기 | 다음 달, 3개월 내 | P1, P3, P4, P5 |
| `visitSchedule` | 방문 일정 | (날짜) | P2, P3, P5 |
| `procedurePlan` | 시술 계획 | (자유 텍스트) | P3, P5 |

### 자동 계산 슬롯

| Slot | 입력 소스 | 계산 방식 | 사용 페르소나 |
|------|-----------|-----------|-------------|
| `bmi` | `bodyInfo` | 체중(kg) / 키(m)^2 | P1 |
| `regionBucket` | `residenceCountry` + `domesticDistrict` | REGION_BUCKET_MAP 참조 | P4 |

### 시스템 관리 슬롯

| Slot | 설명 | 설정 방식 |
|------|------|-----------|
| `protocolMode` | 시술 프로토콜 모드 | 분기 규칙에 의해 자동 설정 |

---

## 5. 분기 규칙 (Branching Rules)

### P1: BMI 기반 분기 (`p1InformSurgery`)

| 우선순위 | 규칙 | 조건 | protocolMode | 대상 |
|---------|------|------|-------------|------|
| 10 | `ruleBodyFatHigh` | bmi >= 23 | STANDARD | p1InformInfo |
| 20 | `ruleBodyFatLow` | bmi < 23 | LOW-FAT | p1InformInfo |
| 0 | (default) | — | STANDARD | p1InformInfo |

### P2: 시술 유형 분기 (`p2InformSurgery`)

| 우선순위 | 조건 | 대상 |
|---------|------|------|
| 10 | upsellAccept = true | p2InformInfoB (흡입+이식) |
| 20 | upsellAccept = false | p2InformInfoA (흡입 단독) |
| 0 | (default) | p2InformInfoA |

### P2: 이식 유형 분기 (`p2InformInfoB`)

| 우선순위 | 조건 | 대상 |
|---------|------|------|
| 10 | transferType = 일반 | p2Finalize |
| 20 | transferType = 줄기세포 | p2Finalize |
| 0 | (default) | p2Finalize |

### P4: 거주지 기반 분기 (`p4PreCollect`)

| 우선순위 | 규칙 | 조건 | protocolMode | 대상 |
|---------|------|------|-------------|------|
| 20 | `ruleRegionRemote` | residenceCountry = ABROAD | FULL | p4Collect |
| 10 | `ruleRegionSemiRemote` | regionBucket != S1 AND != S2 | SEMI-REMOTE | p4Collect |
| 0 | (default) | — | STANDARD | p4Collect |

### P5: 유방암/보형물 분기 (`p5AskMedical`)

| 우선순위 | 규칙 | 조건 | protocolMode | 대상 |
|---------|------|------|-------------|------|
| 30 | `ruleCancerNone` | breastCancerHistory = false | STANDARD | p5InformSurgery |
| 20 | `ruleCancerConditional` | breastCancerHistory=true + cancerSurgeryType=부분 | CONDITIONAL | p5InformSurgery |
| 10 | `ruleCancerNotAllowed` | breastCancerHistory=true + cancerSurgeryType=완전 | NOT_ALLOWED | p5InformSurgery |
| 0 | (default) | — | STANDARD | p5InformSurgery |

---

## 6. 가이드 선택 규칙 (Guide Selection)

분기 후 각 Step에 여러 Guide가 연결된 경우, `protocolMode`에 따라 적절한 Guide를 선택합니다.

### P1 Guide Selection

| Step | protocolMode | 선택 가이드 |
|------|-------------|-------------|
| p1InformSurgery | STANDARD | `guideGraftInfoStandard` |
| p1InformSurgery | LOW-FAT | `guideGraftInfoLowFat` |

### P4 Guide Selection (전 스텝에 걸쳐 3-way)

| Step | STANDARD | SEMI-REMOTE | FULL |
|------|----------|-------------|------|
| p4PreCollect | `guideStandardPremise` | `guideSemiremotePremise` | `guideAbroadPremise` |
| p4Collect | `guideStandardInbody` | `guideSemiremoteInbody` | `guideAbroadInbody` |
| p4AskLifestyle | `guideStandardRecovery` | `guideSemiremoteLogic` | `guideAbroadLogic` |
| p4AskDetail | — | `guideSemiremoteProcess` | `guideAbroadProcess` |
| p4InformSurgery | `guideStandardProcess` | `guideSemiremoteRoute` | `guideAbroadProtocol` |
| p4InformInfo | `guideStandardUpload` | `guideSemiremoteUpload` | `guideAbroadUpload` |
| p4Confirm | `guideStandardBooking` | `guideSemiremoteBooking` | `guideAbroadBooking` |
| p4Finalize | `guideStandardPostCare` | `guideSemiremotePostCare` | `guideAbroadPostCare` |

---

## 7. 자동 계산 및 조건부 스킵

### 자동 계산 (AUTO_COMPUTABLE_SLOTS)

| Slot | 필요 입력 | 계산 방식 |
|------|-----------|-----------|
| `bmi` | `bodyInfo` (키/체중) | BMI = weight(kg) / height(m)^2 |
| `regionBucket` | `residenceCountry` (+`domesticDistrict`) | 해외 → ABROAD, 국내 → S1~S6 매핑 |

### 조건부 스킵 (CONDITIONAL_SKIP_RULES)

| 스킵 대상 | 선행 조건 | 설명 |
|-----------|-----------|------|
| `implantCondition` | implantPresence = false | 보형물 없으면 상태 불필요 |
| `implantOriginHospital` | implantPresence = false | 보형물 없으면 병원 불필요 |
| `domesticDistrict` | residenceCountry = ABROAD | 해외 거주 시 국내 지역구 불필요 |
| `weightGainPlan` | weightGainIntent = false | 증량 의사 없으면 계획 불필요 |
| `nutritionConsult` | weightGainIntent = false | 증량 의사 없으면 영양 상담 불필요 |
| `inbodyPhotoUpload` | inbodyAvailable = false | InBody 없으면 사진 업로드 불필요 |
| `pastOpsSite` | pastOps = 없음/false/none/처음 | 과거 시술 없으면 부위 불필요 |

---

## 8. 프로그램 및 부작용

### 프로그램 목록

| Program ID | 대상 페르소나 | 설명 |
|-----------|-------------|------|
| `lowFatCustromProgram` | P1 (slimBody) | 체지방 기준 검증, 체중 증량/영양 관리/사전 검진 포함 맞춤 프로그램 |
| `lipoStandalone` | P2 (lipoCustomer) | 불필요 지방 제거로 라인 개선. 압박복/관리 안내 포함 |
| `lipoGraftCombined` | P2 (lipoCustomer) | 흡입으로 채취 후, 가슴 볼륨 보완을 위한 이식 |
| `stemCellGraft` | P2 (lipoCustomer) | 지방 채취 → 농축/처리 → 주입. 생착률/유지력 중심 |
| `faceAntiAgingProgram` | P3 (skinTreatment) | 가슴성형 전후 피부관리 (탄력 회복/흉터 관리/피부 재생) 맞춤 프로그램 |
| `longDistanceProgram` | P4 (longDistance) | 원격 사전 준비 + 일정 압축 설계 (동등 생착률 목표) |
| `revisionGraftProgram` | P5 (revisionFatigue) | 제거-이식-사후관리 통합 설계 재수술 맞춤 프로그램 |

### 프로그램별 부작용

| Program | 부작용 |
|---------|--------|
| `lowFatCustromProgram` | swelling, bruising, pain, mobilityDiscomfort, recoverySpeedVar |
| `lipoStandalone` | swelling, bruising, pain, contourIrregularity |
| `lipoGraftCombined` | suctionRecoveryVar, graftSurvialVar |
| `stemCellGraft` | swelling, pain, graftSurvialVar |
| `faceAntiAgingProgram` | swelling, bruising, tempPain, effectDurationVar |
| `longDistanceProgram` | swelling, bruising, pain, mobilityDiscomfort, recoverySpeedVar |
| `revisionGraftProgram` | swelling, bruising, pain, recoverySpeedVar, scarring, sensoryChange |

### Surgery 노드 (벡터 검색용)

| Surgery ID | 부작용 |
|-----------|--------|
| Surgery_BreastAugmentation | SE_Swelling, SE_Bruising, SE_CapsularContracture, SE_Numbness, SE_Scarring |
| Surgery_BreastReduction | SE_Swelling, SE_Bruising, SE_Scarring, SE_Numbness |
| Surgery_FatTransfer | SE_Swelling, SE_Bruising, SE_FatAbsorption |
| Surgery_Rhinoplasty | SE_Swelling, SE_Bruising, SE_Numbness |
| Surgery_FaceContour | SE_Swelling, SE_Numbness, SE_Scarring |
| Surgery_Blepharoplasty | SE_Swelling, SE_Bruising |

---

## 9. 그래프 통계 요약

| 항목 | 수량 |
|------|------|
| 총 노드 | 268 |
| 총 관계 | 497 |
| 페르소나 (메인) | 5 |
| 페르소나 (레거시) | 2 |
| 시나리오 | 7 |
| 스텝 | 35 |
| 체크아이템 (슬롯) | 78 |
| 가이드 | 44 |
| 프로그램 | 7 |
| 결정 규칙 | 21 |
| 조건 | 24 |
| 옵션 | 9 |
| 수술 유형 | 6 |
| 부작용 | 18 |
| 분기 포인트 | 5 (P1:1, P2:2, P4:1, P5:1) |
| 벡터 인덱스 | 3 (Surgery, Step, CheckItem) |
| 고유 슬롯 수 | ~65+ |

### 레거시 페르소나 (참조)

| ID | 시나리오 | 비고 |
|----|---------|------|
| P1_BreastConsult | SC_BreastConsult | 스텝 없음 (구 버전) |
| P2_FaceConsult | SC_FaceConsult | 스텝 없음 (구 버전) |
