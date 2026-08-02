# -*- coding: utf-8 -*-
"""各種可重建展示／基準 seed 共用的候選假資料 schema。

姓名僅為自然語感候選，待維護者對照真實名單核准；不得據此宣稱已證明
不對應真人。Task D 可直接匯入 ``FAKE_DATA``，避免另維護人員 ID 與文案。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PersonnelSeed:
    staff_id: str
    name: str
    alias: str = ""


@dataclass(frozen=True)
class DocumentTextSeed:
    task_subject: str
    criminal_reason: str
    general_subject: str
    reward_reason: str
    long_text: str


@dataclass(frozen=True)
class FakeSeedData:
    agency_name: str
    personnel: tuple[PersonnelSeed, ...]
    documents: DocumentTextSeed


FAKE_DATA = FakeSeedData(
    agency_name="青川分局",
    personnel=(
        PersonnelSeed("P01", "王小明", "小明"),
        PersonnelSeed("P02", "李小華", "小華"),
        PersonnelSeed("P03", "陳大華", "大華"),
        PersonnelSeed("P04", "林小美", "小美"),
        PersonnelSeed("P05", "張大同", "大同"),
        PersonnelSeed("P06", "吳小芳", "小芳"),
    ),
    documents=DocumentTextSeed(
        task_subject="請各組彙整本月社區治安座談會執行情形並依限回報",
        criminal_reason="查獲涉嫌竊盜案件，檢附初步調查資料陳報",
        general_subject="檢送本月巡守隊聯繫會報紀錄一份，請查照",
        reward_reason="辦理社區安全宣導及協助查緝工作表現積極",
        long_text=(
            "請各單位彙整轄內社區治安座談、校園安全宣導與重要節日勤務執行情形，"
            "並逐項核對出勤紀錄、成果照片及後續追蹤事項後，依規定格式於期限內回報；"
            "如有跨單位協調需求，請一併敘明辦理進度、權責分工與預定完成日期，"
            "以利統整後續會議資料及勤務規劃。"
        ),
    ),
)
