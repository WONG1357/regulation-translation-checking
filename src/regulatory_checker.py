from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re

from src.schemas import (
    BilingualPair,
    DetectedRegulation,
    RegulatoryFinding,
    Severity,
)
from src.utils import stable_id


@dataclass(frozen=True)
class RegulatoryCoverageTopic:
    clause: str
    title: str
    expected_evidence: str
    keywords: tuple[str, ...]
    severity_if_missing: str = "Major"


ISO_13485_COVERAGE_TOPICS = (
    RegulatoryCoverageTopic(
        "4.1",
        "Quality management system - general requirements",
        "QMS scope/processes and interaction or process approach evidence.",
        ("质量管理体系", "Quality Management System", "process", "过程"),
    ),
    RegulatoryCoverageTopic(
        "4.2.3",
        "Medical device file",
        "Medical device file / technical file / device documentation requirements.",
        ("医疗器械文档", "Medical Device File", "MDF", "technical file"),
    ),
    RegulatoryCoverageTopic(
        "4.2.4",
        "Control of documents",
        "Document approval, review, update, availability, and obsolete document control.",
        ("文件控制", "Control of Documents", "Document Control", "QSP0401"),
    ),
    RegulatoryCoverageTopic(
        "4.2.5",
        "Control of records",
        "Record identification, storage, protection, retention, and disposition.",
        ("记录控制", "Control of Records", "Record Control", "record", "记录"),
    ),
    RegulatoryCoverageTopic(
        "5.1",
        "Management commitment",
        "Top management commitment to QMS effectiveness and regulatory/customer requirements.",
        ("管理承诺", "Management Commitment", "top management", "总经理"),
    ),
    RegulatoryCoverageTopic(
        "5.3",
        "Quality policy",
        "Quality policy and communication/maintenance evidence.",
        ("质量方针", "Quality policy"),
    ),
    RegulatoryCoverageTopic(
        "5.4",
        "Planning and quality objectives",
        "Quality objectives and QMS planning evidence.",
        ("质量目标", "Quality objective", "策划", "Planning"),
    ),
    RegulatoryCoverageTopic(
        "5.5.1",
        "Responsibility and authority",
        "Responsibility/authority assignment and communication.",
        ("职责", "权限", "Responsibility", "authority"),
    ),
    RegulatoryCoverageTopic(
        "5.5.2",
        "Management representative",
        "Management Representative role and responsibility evidence.",
        ("管理者代表", "Management Representative", "MR"),
    ),
    RegulatoryCoverageTopic(
        "5.6",
        "Management review",
        "Management review input/output and review process evidence.",
        ("管理评审", "Management Review", "QSP0501"),
    ),
    RegulatoryCoverageTopic(
        "6.2",
        "Human resources / competence",
        "Competence, training, awareness, and personnel qualification evidence.",
        ("培训", "Training", "competence", "能力", "人力资源"),
    ),
    RegulatoryCoverageTopic(
        "6.3",
        "Infrastructure",
        "Infrastructure/equipment/building/process support evidence.",
        ("基础设施", "Infrastructure", "设备", "Equipment"),
    ),
    RegulatoryCoverageTopic(
        "6.4",
        "Work environment and contamination control",
        "Work environment, cleanliness, contamination control, or cleanroom evidence.",
        ("工作环境", "污染控制", "Work environment", "contamination", "clean room"),
    ),
    RegulatoryCoverageTopic(
        "7.1",
        "Planning of product realization / risk management",
        "Product realization planning and risk-management linkage.",
        ("产品实现", "风险管理", "Risk Management", "Planning of product realization"),
    ),
    RegulatoryCoverageTopic(
        "7.2",
        "Customer-related processes",
        "Customer requirements, contract review, communication, complaints or feedback.",
        ("客户", "顾客", "Customer", "contract review"),
    ),
    RegulatoryCoverageTopic(
        "7.3",
        "Design and development",
        "Design and development planning, inputs, outputs, review, verification, validation, transfer, changes, and files.",
        ("设计和开发", "Design and development", "DHF", "设计开发"),
    ),
    RegulatoryCoverageTopic(
        "7.4",
        "Purchasing",
        "Supplier evaluation, purchasing information, purchased product verification.",
        ("采购", "Purchasing", "供应商", "Supplier", "SCAR"),
    ),
    RegulatoryCoverageTopic(
        "7.5",
        "Production and service provision",
        "Production control, validation, cleanliness, installation/service applicability, identification and traceability.",
        ("生产", "Production", "service provision", "traceability", "可追溯"),
    ),
    RegulatoryCoverageTopic(
        "7.6",
        "Monitoring and measuring equipment",
        "Calibration/control of monitoring and measuring equipment.",
        ("监控和测量", "校准", "Calibration", "measuring equipment"),
    ),
    RegulatoryCoverageTopic(
        "8.2.1",
        "Feedback",
        "Feedback process and use as input to risk/monitoring processes.",
        ("反馈", "Feedback"),
    ),
    RegulatoryCoverageTopic(
        "8.2.2",
        "Complaint handling",
        "Complaint handling and investigation/evaluation evidence.",
        ("投诉", "Complaint", "customer complaint"),
    ),
    RegulatoryCoverageTopic(
        "8.2.3",
        "Reporting to regulatory authorities",
        "Regulatory reporting/adverse event/authority notification evidence.",
        ("监管机构", "regulatory authorities", "reporting", "监管策略"),
    ),
    RegulatoryCoverageTopic(
        "8.2.4",
        "Internal audit",
        "Internal audit planning, execution, reporting, and follow-up evidence.",
        ("内部审核", "Internal Audit", "audit"),
    ),
    RegulatoryCoverageTopic(
        "8.3",
        "Control of nonconforming product",
        "Nonconforming product identification, control, disposition, concession/rework evidence.",
        ("不合格品", "Nonconforming", "MRB"),
    ),
    RegulatoryCoverageTopic(
        "8.4",
        "Analysis of data",
        "Data analysis/statistical technique and QMS performance evidence.",
        ("数据分析", "Analysis of data", "statistical"),
    ),
    RegulatoryCoverageTopic(
        "8.5.2",
        "Corrective action",
        "Corrective action process, root cause, action, effectiveness evidence.",
        ("纠正措施", "Corrective Action", "CAPA", "CPAR"),
    ),
    RegulatoryCoverageTopic(
        "8.5.3",
        "Preventive action",
        "Preventive action process and effectiveness evidence.",
        ("预防措施", "Preventive Action", "CPAR"),
    ),
)

SEVERITY_RANK = {
    "None": 0,
    "Observation": 1,
    "Minor": 2,
    "Major": 3,
    "Critical": 4,
}


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _topic_match_score(topic: RegulatoryCoverageTopic, pair: BilingualPair) -> int:
    haystack = _normalise(
        " ".join(
            [
                pair.section or "",
                pair.chinese_text,
                pair.english_text,
                pair.machine_translated_english,
            ]
        )
    )
    score = 0
    if pair.section and (
        pair.section == topic.clause or pair.section.startswith(f"{topic.clause}.")
    ):
        score += 5
    for keyword in topic.keywords:
        if _normalise(keyword) in haystack:
            score += 2
    return score


def _evidence_summary(matches: list[BilingualPair]) -> str:
    parts = []
    for pair in matches[:3]:
        excerpt = pair.english_text or pair.machine_translated_english or pair.chinese_text
        parts.append(
            f"p.{pair.page} §{pair.section or '—'}: "
            + re.sub(r"\s+", " ", excerpt)[:220]
        )
    return "\n".join(parts)


def build_regulatory_coverage_matrix(
    pairs: list[BilingualPair],
    regulations: list[DetectedRegulation],
    findings: list[RegulatoryFinding] | None = None,
) -> list[dict[str, str]]:
    """Build a practical selected-regulation-to-document-section coverage matrix."""
    if not regulations:
        return []
    target = regulations[0]
    findings = findings or []
    finding_by_topic: dict[str, list[RegulatoryFinding]] = defaultdict(list)
    for finding in findings:
        key = finding.clause_or_topic.split()[0] if finding.clause_or_topic else ""
        if key:
            finding_by_topic[key].append(finding)

    topics = ISO_13485_COVERAGE_TOPICS
    usable_pairs = [
        pair
        for pair in pairs
        if pair.chinese_text
        and pair.pair_status in {"confirmed", "uncertain"}
        and pair.block_type not in {"header", "footer", "reference_table"}
    ]
    rows: list[dict[str, str]] = []
    for topic in topics:
        scored = [
            (score, pair)
            for pair in usable_pairs
            if (score := _topic_match_score(topic, pair)) > 0
        ]
        scored.sort(key=lambda item: (-item[0], item[1].page, item[1].section or ""))
        matches = [pair for _, pair in scored[:8]]
        related_findings = finding_by_topic.get(topic.clause, [])
        if related_findings:
            worst = max(
                related_findings,
                key=lambda item: SEVERITY_RANK.get(item.severity.value, 0),
            )
            decision = worst.decision or "Manual Review Required"
            severity = worst.severity.value
            gap = worst.gap_or_concern or worst.issue
            recommendation = worst.recommendation
        elif not matches:
            decision = "Missing Evidence"
            severity = topic.severity_if_missing
            gap = "No mapped company-document evidence found for this selected-regulation topic."
            recommendation = "Confirm whether the Quality Manual or a referenced procedure covers this topic; add or reference evidence if missing."
        elif any("qsp" in _normalise(pair.chinese_text + " " + pair.english_text) for pair in matches):
            decision = "Partially Compliant"
            severity = "Observation"
            gap = "Mapped evidence includes supporting procedure references; underlying procedures were not reviewed in this upload."
            recommendation = "Review referenced procedures to confirm detailed implementation."
        else:
            decision = "Mapped / Evidence Found"
            severity = "None"
            gap = "No gap identified from mapped Quality Manual evidence."
            recommendation = "No immediate action from mapping view; confirm detail in supporting procedures where applicable."

        rows.append(
            {
                "Selected regulation": target.name,
                "Regulation clause/subsection": topic.clause,
                "Regulation topic": topic.title,
                "Expected evidence": topic.expected_evidence,
                "Company file chapter/subsection": ", ".join(
                    sorted({pair.section or "—" for pair in matches})
                )
                or "Not found",
                "Page references": ", ".join(
                    str(page) for page in sorted({pair.page for pair in matches})
                )
                or "—",
                "Mapped evidence": _evidence_summary(matches) or "No mapped evidence found.",
                "Coverage decision": decision,
                "Severity": severity,
                "Gap / missing content": gap,
                "Recommended action": recommendation,
            }
        )
    return rows


def deterministic_regulatory_observations(
    pairs: list[BilingualPair], regulations: list[DetectedRegulation]
) -> list[RegulatoryFinding]:
    findings: list[RegulatoryFinding] = []
    names = {reg.name for reg in regulations}
    if "EU MDD 93/42/EEC" in names and "EU MDR Regulation (EU) 2017/745" in names:
        evidence = next(reg for reg in regulations if reg.name == "EU MDD 93/42/EEC")
        findings.append(
            RegulatoryFinding(
                finding_id=stable_id("RF", "mdd-mdr"),
                regulation="EU MDD 93/42/EEC / EU MDR 2017/745",
                clause_or_topic="Regulatory applicability and transition status",
                page=evidence.page,
                section=evidence.section,
                issue="Both legacy MDD and EU MDR are listed without an explicit applicability/status explanation.",
                severity=Severity.observation,
                explanation=(
                    "The document should make clear whether a legacy reference is retained for "
                    "historical, transitional, market-specific, or active QMS purposes."
                ),
                recommendation=(
                    "Have a qualified regulatory professional verify the current applicability "
                    "and label legacy references clearly; do not treat this observation as a legal conclusion."
                ),
                confidence=0.76,
                manual_review_required=True,
            )
        )
    for reg in regulations:
        if "CMDCAS" in reg.evidence_text.upper():
            findings.append(
                RegulatoryFinding(
                    finding_id=stable_id("RF", "cmdcas", reg.page),
                    regulation=reg.name,
                    clause_or_topic="Regulatory program naming",
                    page=reg.page,
                    section=reg.section,
                    issue="The document uses the CMDCAS program name.",
                    severity=Severity.observation,
                    explanation="Program and market references can become outdated over time.",
                    recommendation=(
                        "Verify the current Canadian conformity-assessment terminology and the "
                        "document's intended historical context."
                    ),
                    confidence=0.72,
                    manual_review_required=True,
                )
            )
    return findings
