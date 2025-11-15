from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError, BulkWriteError
from dotenv import load_dotenv
import os

# Load environment variables from .env (in this folder or repo root)
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI not set in environment or .env (see api/README.md)")

# Connect to MongoDB Atlas
client = MongoClient(MONGODB_URI)
db = client["softwarelabdb"]

# Collections (match original names so Load Project works)
users_col = db.get_collection("Users")       # new for auth; will be created on first insert
projects_col = db.get_collection("Projects")
resources_col = db.get_collection("Resources")


# Ensure uniqueness
users_col.create_index("userId", unique=True)
projects_col.create_index("projectId", unique=True)
# add compound unique index for resources to prevent duplicates (safe-guard)
try:
    resources_col.create_index([("projectId", 1), ("hwsetId", 1)], unique=True)
except Exception:
    # ignore index creation errors at startup
    pass

app = Flask(__name__)

# Allow local dev frontend and Heroku frontend
CORS(
    app,
    origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "https://sftwrlab-frontend-58557d195db3.herokuapp.com",
    ],
    supports_credentials=True,
)


# ---------- HELPER FUNCTIONS ----------

def check_project_access(project_id, user_id):
    """Check if user has access to the project"""
    if not user_id:
        return False
    
    project = projects_col.find_one({"projectId": project_id})
    if not project:
        return False
    
    # Check if user is in members list or project is public
    return (user_id in project.get("members", []) or 
            project.get("isPublic", False))

def get_user_projects(user_id):
    """Get projects where user is a member (created or invited)"""
    if not user_id:
        return []
    
    # Find only projects where user is a member
    query = {"members": user_id}
    
    return list(projects_col.find(query, {
        "_id": 0, "projectId": 1, "name": 1, "description": 1, 
        "createdAt": 1, "createdBy": 1, "isPublic": 1
    }))

def get_public_projects():
    """Get all public projects that users can discover and join"""
    return list(projects_col.find(
        {"isPublic": True},
        {"_id": 0, "projectId": 1, "name": 1, "description": 1, 
         "createdAt": 1, "createdBy": 1, "isPublic": 1}
    ))

# ---------- AUTH ENDPOINTS ----------

@app.route("/api/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True) or {}
    user_id = data.get("userId")
    password = data.get("password")

    if not user_id or not password:
        return jsonify({"error": "userId and password are required"}), 400

    doc = {
        "userId": user_id,
        "password": password,  # for class/demo only; don't do this in real life :)
    }

    try:
        users_col.insert_one(doc)
    except DuplicateKeyError:
        return jsonify({"error": "User already exists"}), 409

    return jsonify({"ok": True, "userId": user_id}), 201


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    user_id = data.get("userId")
    password = data.get("password")

    if not user_id or not password:
        return jsonify({"error": "userId and password are required"}), 400

    user = users_col.find_one({"userId": user_id})
    if not user or user.get("password") != password:
        # Covers: wrong password OR non-existent user
        return jsonify({"error": "Invalid userId/password"}), 401

    # Simple response so frontend can store/log state
    return jsonify({"ok": True, "userId": user_id}), 200


# ---------- PROJECT ENDPOINTS (already in your README spec) ----------

@app.route("/api/projects", methods=["GET"])
def list_projects():
    # Get userId from query parameter for authorization
    user_id = request.args.get("userId")
    
    if user_id:
        # Return only projects accessible to this user
        docs = get_user_projects(user_id)
    else:
        # Return only public projects if no user specified
        docs = list(projects_col.find(
            {"isPublic": True},
            {"_id": 0, "projectId": 1, "name": 1, "description": 1, "createdAt": 1, "isPublic": 1}
        ))
    
    return jsonify(docs), 200


@app.route("/api/projects/public", methods=["GET"])
def list_public_projects():
    """Get all public projects that users can discover and join"""
    docs = get_public_projects()
    return jsonify(docs), 200


@app.route("/api/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    user_id = request.args.get("userId")
    
    # Check authorization
    if not check_project_access(project_id, user_id):
        return jsonify({"error": "Access denied"}), 403
    
    doc = projects_col.find_one(
        {"projectId": project_id},
        {"_id": 0, "projectId": 1, "name": 1, "description": 1, "createdAt": 1, 
         "createdBy": 1, "members": 1, "isPublic": 1},
    )
    if not doc:
        return jsonify({"error": "Project not found"}), 404
    return jsonify(doc), 200


@app.route("/api/projects/<project_id>/visibility", methods=["PATCH"])
def set_project_visibility(project_id):
    payload = request.get_json(force=True) or {}
    user_id = payload.get("userId")
    if not user_id:
        return jsonify({"error": "userId is required"}), 400

    project = projects_col.find_one({"projectId": project_id})
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Only the creator may change visibility
    if project.get("createdBy") != user_id:
        return jsonify({"error": "Only the project owner may change visibility"}), 403

    is_public = bool(payload.get("isPublic", False))
    projects_col.update_one({"projectId": project_id}, {"$set": {"isPublic": is_public}})
    return jsonify({"ok": True, "isPublic": is_public}), 200


@app.route("/api/projects", methods=["POST"])
def create_project():
    payload = request.get_json(force=True) or {}
    required = ("projectId", "name", "createdBy")
    if not all(k in payload and payload[k] for k in required):
        return jsonify({"error": "projectId, name, and createdBy are required"}), 400

    created_by = payload["createdBy"]
    
    # Verify user exists
    user = users_col.find_one({"userId": created_by})
    if not user:
        return jsonify({"error": "Invalid user"}), 400

    doc = {
        "projectId": payload["projectId"],
        "name": payload["name"],
        "description": payload.get("description", ""),
        "createdAt": payload.get("createdAt"),
        "createdBy": created_by,
        "members": [created_by],  # Creator is automatically a member
        "isPublic": payload.get("isPublic", False)
    }

    try:
        projects_col.insert_one(doc)
    except DuplicateKeyError:
        return jsonify({"error": "projectId already exists"}), 409
    except Exception as e:
        # unexpected error while creating project
        return jsonify({"error": f"Failed to create project: {str(e)}"}), 500

    # Create default hardware resources for the new project (create one-by-one to avoid BulkWrite crashes)
    default_hw1_total = int(payload.get("default_hwset1_total", 15))
    default_hw2_total = int(payload.get("default_hwset2_total", 10))

    default_resources = [
        {
            "projectId": doc["projectId"],
            "hwsetId": "HWSet1",
            "name": "Arduino Uno Kit",
            "total": default_hw1_total,
            "allocatedToProject": 0,
            "available": default_hw1_total,
            "notes": f"Default Arduino kits for {doc['projectId']}"
        },
        {
            "projectId": doc["projectId"],
            "hwsetId": "HWSet2",
            "name": "Raspberry Pi Kit",
            "total": default_hw2_total,
            "allocatedToProject": 0,
            "available": default_hw2_total,
            "notes": f"Default Raspberry Pi kits for {doc['projectId']}"
        }
    ]

    created_or_existing_resources = []
    for res_doc in default_resources:
        try:
            resources_col.insert_one(res_doc)
            created_or_existing_resources.append({
                "projectId": res_doc["projectId"],
                "hwsetId": res_doc["hwsetId"],
                "name": res_doc["name"],
                "total": res_doc["total"],
                "allocatedToProject": res_doc["allocatedToProject"],
                "available": res_doc["available"],
                "notes": res_doc.get("notes", "")
            })
        except DuplicateKeyError:
            # resource already exists — fetch current state
            existing = resources_col.find_one(
                {"projectId": res_doc["projectId"], "hwsetId": res_doc["hwsetId"]},
                {"_id": 0, "projectId": 1, "hwsetId": 1, "name": 1, "total": 1, "allocatedToProject": 1, "available": 1, "notes": 1}
            )
            if existing:
                created_or_existing_resources.append(existing)
        except Exception:
            # any other error — attempt to fetch existing and continue
            existing = resources_col.find_one(
                {"projectId": res_doc["projectId"], "hwsetId": res_doc["hwsetId"]},
                {"_id": 0, "projectId": 1, "hwsetId": 1, "name": 1, "total": 1, "allocatedToProject": 1, "available": 1, "notes": 1}
            )
            if existing:
                created_or_existing_resources.append(existing)

    return jsonify({
        "ok": True,
        "projectId": doc["projectId"],
        "resources": created_or_existing_resources
    }), 201


@app.route("/api/projects/<project_id>/join", methods=["POST"])
def join_project(project_id):
    try:
        payload = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON body"}), 400

    user_id = payload.get("userId")
    if not user_id:
        return jsonify({"error": "userId is required"}), 400

    try:
        # Verify user exists
        user = users_col.find_one({"userId": user_id})
        if not user:
            return jsonify({"error": "Invalid user"}), 400

        # Find project
        project = projects_col.find_one({"projectId": project_id})
        if not project:
            return jsonify({"error": "Project not found"}), 404

        # Check if project is public or user is already a member
        if not project.get("isPublic", False) and user_id not in project.get("members", []):
            return jsonify({"error": "Access denied - project is private"}), 403

        # Add user to members if not already there
        if user_id not in project.get("members", []):
            projects_col.update_one(
                {"projectId": project_id},
                {"$addToSet": {"members": user_id}}
            )
            return jsonify({"ok": True, "message": "Successfully joined project"}), 200
        else:
            return jsonify({"ok": True, "message": "Already a member of this project"}), 200

    except Exception as e:
        # Log and return a safe error for debugging in dev
        print("Error in join_project:", e)
        return jsonify({"error": "Internal server error", "detail": str(e)}), 500


@app.route("/api/projects/<project_id>/members", methods=["GET"])
def get_project_members(project_id):
    user_id = request.args.get("userId")
    
    # Check authorization
    if not check_project_access(project_id, user_id):
        return jsonify({"error": "Access denied"}), 403
    
    project = projects_col.find_one({"projectId": project_id})
    if not project:
        return jsonify({"error": "Project not found"}), 404
    
    members = project.get("members", [])
    return jsonify({
        "members": members,
        "createdBy": project.get("createdBy"),
        "isPublic": project.get("isPublic", False)
    }), 200


@app.route("/api/projects/<project_id>/members/<member_id>", methods=["DELETE"])
def remove_project_member(project_id, member_id):
    payload = request.get_json(force=True) or {}
    requesting_user = payload.get("requestingUser") or request.args.get("requestingUser")

    if not requesting_user:
        return jsonify({"error": "requestingUser is required"}), 400

    project = projects_col.find_one({"projectId": project_id})
    if not project:
        return jsonify({"error": "Project not found"}), 404

    # Only the creator may remove members
    if project.get("createdBy") != requesting_user:
        return jsonify({"error": "Only the project owner may remove members"}), 403

    # Prevent removing the project owner
    if member_id == project.get("createdBy"):
        return jsonify({"error": "Cannot remove the project owner"}), 400

    result = projects_col.update_one(
        {"projectId": project_id},
        {"$pull": {"members": member_id}}
    )

    if result.modified_count > 0:
        return jsonify({"ok": True, "removed": member_id}), 200
    else:
        return jsonify({"ok": True, "message": "User was not a member"}), 200


@app.route("/api/projects/<project_id>/invite", methods=["POST"])
def invite_to_project(project_id):
    payload = request.get_json(force=True) or {}
    requesting_user = payload.get("requestingUser")
    invite_user = payload.get("inviteUser")
    
    if not requesting_user or not invite_user:
        return jsonify({"error": "requestingUser and inviteUser are required"}), 400
    
    # Check if requesting user has access to project
    if not check_project_access(project_id, requesting_user):
        return jsonify({"error": "Access denied"}), 403
    
    # Verify invited user exists
    user = users_col.find_one({"userId": invite_user})
    if not user:
        return jsonify({"error": "Invited user does not exist"}), 404
    
    # Add user to project members
    result = projects_col.update_one(
        {"projectId": project_id},
        {"$addToSet": {"members": invite_user}}
    )
    
    if result.modified_count > 0:
        return jsonify({"ok": True, "message": f"Successfully invited {invite_user} to project"}), 200
    else:
        return jsonify({"ok": True, "message": f"{invite_user} is already a member"}), 200


# ---------- HARDWARE RESOURCE ENDPOINTS ----------

@app.route("/api/projects/<project_id>/resources", methods=["GET"])
def get_project_resources(project_id):
    user_id = request.args.get("userId")
    
    # Check authorization
    if not check_project_access(project_id, user_id):
        return jsonify({"error": "Access denied"}), 403
    
    docs = list(
        resources_col.find(
            {"projectId": project_id},
            {"_id": 0, "projectId": 1, "hwsetId": 1, "name": 1, "total": 1,
             "allocatedToProject": 1, "available": 1, "notes": 1},
        )
    )
    return jsonify(docs), 200


@app.route("/api/projects/<project_id>/resources/<hwset_id>/checkout", methods=["POST"])
def checkout_hardware(project_id, hwset_id):
    data = request.get_json(force=True) or {}
    quantity = data.get("quantity", 1)
    user_id = data.get("userId")  # Should be passed from frontend
    
    if not user_id:
        return jsonify({"error": "userId is required"}), 400
    
    # Check project authorization
    if not check_project_access(project_id, user_id):
        return jsonify({"error": "Access denied to project"}), 403
    
    if not isinstance(quantity, int) or quantity <= 0:
        return jsonify({"error": "quantity must be a positive integer"}), 400
    
    # Find the resource
    resource = resources_col.find_one({"projectId": project_id, "hwsetId": hwset_id})
    if not resource:
        return jsonify({"error": "Hardware set not found"}), 404
    
    # Check availability
    current_available = resource.get("available", 0)
    if quantity > current_available:
        return jsonify({"error": f"Only {current_available} units available"}), 400
    
    # Update quantities
    new_available = current_available - quantity
    new_allocated = resource.get("allocatedToProject", 0) + quantity
    
    resources_col.update_one(
        {"projectId": project_id, "hwsetId": hwset_id},
        {"$set": {"available": new_available, "allocatedToProject": new_allocated}}
    )
    
    return jsonify({
        "ok": True, 
        "message": f"Checked out {quantity} units of {hwset_id}",
        "available": new_available,
        "allocated": new_allocated
    }), 200


@app.route("/api/projects/<project_id>/resources/<hwset_id>/checkin", methods=["POST"])
def checkin_hardware(project_id, hwset_id):
    data = request.get_json(force=True) or {}
    quantity = data.get("quantity", 1)
    user_id = data.get("userId")  # Should be passed from frontend
    
    if not user_id:
        return jsonify({"error": "userId is required"}), 400
    
    # Check project authorization
    if not check_project_access(project_id, user_id):
        return jsonify({"error": "Access denied to project"}), 403
    
    if not isinstance(quantity, int) or quantity <= 0:
        return jsonify({"error": "quantity must be a positive integer"}), 400
    
    # Find the resource
    resource = resources_col.find_one({"projectId": project_id, "hwsetId": hwset_id})
    if not resource:
        return jsonify({"error": "Hardware set not found"}), 404
    
    # Check if we can check in this many
    current_allocated = resource.get("allocatedToProject", 0)
    if quantity > current_allocated:
        return jsonify({"error": f"Only {current_allocated} units are checked out"}), 400
    
    # Update quantities
    new_allocated = current_allocated - quantity
    new_available = resource.get("available", 0) + quantity
    
    resources_col.update_one(
        {"projectId": project_id, "hwsetId": hwset_id},
        {"$set": {"available": new_available, "allocatedToProject": new_allocated}}
    )
    
    return jsonify({
        "ok": True, 
        "message": f"Checked in {quantity} units of {hwset_id}",
        "available": new_available,
        "allocated": new_allocated
    }), 200


if __name__ == "__main__":
    # Runs on http://127.0.0.1:5000
    app.run(host="127.0.0.1", port=5000, debug=True)

