import re
from collections import Counter

from backend.db import connect


def main():
    with connect() as db:
        rows = db.execute("SELECT c.id,c.category,d.text FROM candidates c JOIN documents d ON d.candidate_id=c.id").fetchall()
    terms = ["FastAPI", "Docker", "Python", "SQL", "Java", "AWS", "React", "machine learning", "recruitment", "Windows Server", "Active Directory", "VMware", "Linux", "network administration"]
    for term in terms:
        matches = [row for row in rows if re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", row["text"], re.I)]
        print(term, len(matches), Counter(row["category"] for row in matches).most_common(5))
    print("FastAPI and Docker", sum(bool(re.search(r"\bfastapi\b", row["text"], re.I) and re.search(r"\bdocker\b", row["text"], re.I)) for row in rows))


if __name__ == "__main__":
    main()
