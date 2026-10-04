# Seed Firestore with initial requirements and architecture mappings
import datetime
from google.cloud import firestore

PROJECT_ID = "qwiklabs-gcp-03-f94ecd44b48d"

db = firestore.Client(project=PROJECT_ID, database="(default)")

INITIAL_REQUIREMENTS = [
    {
        "requirement_id": "REQ-101",
        "business_goal": "Real-time payment transaction fraud detection under 100ms response time.",
        "mapped_component": "Vertex AI Real-time Inference Pipeline & Pub/Sub Subscriptions",
        "coverage_status": "Covered",
        "risk_level": "Low",
        "remediation_notes": "SLA met via regional Vertex AI endpoints.",
    },
    {
        "requirement_id": "REQ-102",
        "business_goal": "Automated audit trail logging for all data access compliant with PCI-DSS 4.0.",
        "mapped_component": "Cloud Audit Logs & BigQuery Security Analytics Export",
        "coverage_status": "Covered",
        "risk_level": "Low",
        "remediation_notes": "Log sinks routed to immutable BigQuery dataset.",
    },
    {
        "requirement_id": "REQ-103",
        "business_goal": "Multi-region failover and disaster recovery with RPO < 5 minutes and RTO < 15 minutes.",
        "mapped_component": "Multi-Region Cloud Spanner Database Cluster",
        "coverage_status": "Partial",
        "risk_level": "Medium",
        "remediation_notes": "Spanner handles DB failover; frontend traffic routing failover policy needs Cloud DNS routing policy configuration.",
    },
    {
        "requirement_id": "REQ-104",
        "business_goal": "End-to-end customer PII redaction before sending prompt payloads to external LLMs.",
        "mapped_component": "Unassigned / Pending Gateway Component",
        "coverage_status": "Gap",
        "risk_level": "High",
        "remediation_notes": "Requires Model Armor or Sensitive Data Protection (DLP) egress proxy integration.",
    },
]

def seed():
    print(f"Seeding Firestore collection 'requirements' in project {PROJECT_ID}...")
    collection_ref = db.collection("requirements")
    for req in INITIAL_REQUIREMENTS:
        doc_ref = collection_ref.document(req["requirement_id"])
        data = {
            **req,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        doc_ref.set(data)
        print(f"  ✓ Seeded {req['requirement_id']}: {req['business_goal'][:50]}... [{req['coverage_status']}]")
    print("Done seeding Firestore!")

if __name__ == "__main__":
    seed()
