"""Editable example JDs for every job family in the primary CSV."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CATEGORY_TEMPLATES = {
    "ACCOUNTANT": ("Accountant", ["financial reporting", "account reconciliation", "tax preparation"], ["Excel", "audit support"]),
    "ADVOCATE": ("Legal Advocate", ["legal research", "case preparation", "client representation"], ["contract review", "court filings"]),
    "AGRICULTURE": ("Agriculture Specialist", ["crop management", "field operations", "soil assessment"], ["farm equipment", "data analysis"]),
    "APPAREL": ("Apparel Production Specialist", ["garment production", "quality control", "vendor coordination"], ["inventory planning", "design collaboration"]),
    "ARTS": ("Arts Program Coordinator", ["creative project delivery", "event coordination", "community engagement"], ["budget planning", "digital media"]),
    "AUTOMOBILE": ("Automotive Technician", ["vehicle diagnostics", "preventive maintenance", "repair documentation"], ["electrical systems", "customer communication"]),
    "AVIATION": ("Aviation Operations Specialist", ["flight operations support", "safety procedures", "regulatory documentation"], ["crew scheduling", "incident reporting"]),
    "BANKING": ("Banking Operations Analyst", ["banking operations", "account servicing", "risk controls"], ["Excel", "customer communication"]),
    "BPO": ("Customer Operations Specialist", ["customer support", "case resolution", "service quality"], ["process improvement", "Excel"]),
    "BUSINESS-DEVELOPMENT": ("Business Development Manager", ["prospecting", "client relationship management", "sales pipeline"], ["market research", "contract negotiation"]),
    "CHEF": ("Chef", ["menu planning", "food preparation", "kitchen safety"], ["inventory control", "team supervision"]),
    "CONSTRUCTION": ("Construction Project Coordinator", ["site coordination", "construction scheduling", "safety compliance"], ["cost estimating", "vendor management"]),
    "CONSULTANT": ("Business Consultant", ["client discovery", "business analysis", "recommendation delivery"], ["project management", "stakeholder management"]),
    "DESIGNER": ("Visual Designer", ["visual design", "design documentation", "client feedback"], ["digital media", "brand systems"]),
    "DIGITAL-MEDIA": ("Digital Media Specialist", ["content production", "social media campaigns", "performance reporting"], ["analytics", "visual design"]),
    "ENGINEERING": ("Engineering Specialist", ["technical design", "system testing", "engineering documentation"], ["project management", "quality assurance"]),
    "FINANCE": ("Financial Analyst", ["financial modeling", "budget analysis", "variance reporting"], ["Excel", "Power BI"]),
    "FITNESS": ("Fitness Coach", ["exercise programming", "client assessment", "safety instruction"], ["group coaching", "progress tracking"]),
    "HEALTHCARE": ("Healthcare Operations Coordinator", ["patient coordination", "clinical documentation", "privacy procedures"], ["quality improvement", "staff scheduling"]),
    "HR": ("Human Resources Specialist", ["employee relations", "recruiting", "policy administration"], ["Excel", "training coordination"]),
    "INFORMATION-TECHNOLOGY": ("IT Support Engineer", ["technical support", "system administration", "network troubleshooting"], ["Linux", "Windows Server"]),
    "PUBLIC-RELATIONS": ("Public Relations Specialist", ["media relations", "press writing", "campaign coordination"], ["event planning", "crisis communication"]),
    "SALES": ("Sales Account Executive", ["prospecting", "client presentations", "account management"], ["CRM reporting", "contract negotiation"]),
    "TEACHER": ("Classroom Teacher", ["lesson planning", "classroom instruction", "student assessment"], ["curriculum design", "parent communication"]),
}


def all_roles():
    evaluated = (("data_scientist", "Data Scientist"), ("hr_analyst", "HR Analyst"),
                 ("it_infrastructure_engineer", "IT Infrastructure Engineer"))
    roles = [{"id": key, "title": title, "group": "Evaluated demo roles", "evaluated": True,
              "text": (ROOT / "data" / "demo" / f"{key}_jd.txt").read_text(encoding="utf-8")}
             for key, title in evaluated]
    for category, (title, required, preferred) in CATEGORY_TEMPLATES.items():
        text = "\n".join([title, "Required qualifications:",
                          *[f"Required: {item}" for item in required],
                          "Preferred qualifications:",
                          *[f"Preferred: {item}" for item in preferred],
                          "Review and edit these example criteria for your actual opening."])
        roles.append({"id": f"category_{category.lower().replace('-', '_')}", "title": title,
                      "category": category, "group": "Dataset job families", "evaluated": False,
                      "text": text})
    return roles
