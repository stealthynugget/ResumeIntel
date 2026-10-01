import json
import sys


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    pool = json.load(open("evaluation/review_pool.json", encoding="utf-8"))
    for role in pool:
        if len(sys.argv) > 1 and role["job"] != sys.argv[1]:
            continue
        print("\n", role["job"].upper())
        for candidate in role["pool"]:
            supported = [a["label"] for a in candidate["assessments"] if a["status"] == "matched"]
            gaps = [a["label"] for a in candidate["assessments"] if a["status"] in {"no_evidence", "needs_review"}]
            print(candidate["candidate_id"], candidate["category"], "supported", supported, "gaps", gaps)
            print(candidate["resume_preview"][:750])


if __name__ == "__main__":
    main()
