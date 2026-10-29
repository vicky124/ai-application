"""Reference data for access control: roles (with levels) and the permissions each role holds."""

ROLE_NAMES = ("employee", "manager", "hr", "compliance", "admin")

# name -> (level, description). Higher level = broader access.
ROLE_DEFS = {
    "employee": (10, "Standard employee: policy Q&A"),
    "manager": (20, "People manager: employee access plus team approvals"),
    "hr": (30, "HR operations: manages documents, views users"),
    "compliance": (30, "Compliance: manages documents, views users and audit log"),
    "admin": (100, "Administrator: full access including user management"),
}

# permission code -> description
PERMISSION_DEFS = {
    "chat:use": "Ask questions in the policy assistant",
    "documents:manage": "Upload, replace and delete policy documents",
    "users:read": "View users and roles",
    "users:manage": "Create, update, deactivate users and reset passwords",
    "audit:read": "View the authentication and administration audit log",
}

ROLE_PERMISSIONS = {
    "employee": ["chat:use"],
    "manager": ["chat:use"],
    "hr": ["chat:use", "documents:manage", "users:read"],
    "compliance": ["chat:use", "documents:manage", "users:read", "audit:read"],
    "admin": list(PERMISSION_DEFS),
}

# Demo accounts seeded for local development only (SEED_DEMO_USERS=false in production).
# (username, password, full name, role, department, manager username)
DEMO_USERS = [
    ("mark", "mark123", "Mark Manager", "manager", "Engineering", None),
    ("alice", "alice123", "Alice Employee", "employee", "Engineering", "mark"),
    ("hannah", "hannah123", "Hannah HR", "hr", "HR", None),
    ("carl", "carl123", "Carl Compliance", "compliance", "Legal", None),
    ("root", "root123", "Admin", "admin", "IT", None),
]
