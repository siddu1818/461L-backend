import requests
import sys

BASE = "http://127.0.0.1:5000"

def rpost(path, json):
    url = BASE + path
    return requests.post(url, json=json)

def rget(path, params=None):
    url = BASE + path
    return requests.get(url, params=params)

def expect(resp, code):
    ok = resp.status_code == code
    print(f"{resp.request.method} {resp.url} -> {resp.status_code} (expected {code})")
    try:
        print(resp.json())
    except Exception:
        print(resp.text)
    return ok

def main():
    # Users
    owner = "test_owner_1"
    user = "test_user_1"
    user2 = "test_user_2"

    # Cleanup note: these tests create data in the real database. Run on dev DB only.

    print("1) Signup owner and user")
    expect(rpost("/api/signup", {"userId": owner, "password": "pw"}), 201)
    expect(rpost("/api/signup", {"userId": user, "password": "pw"}), 201)

    print("2) Owner creates private project")
    proj = "private_proj_test_1"
    resp = rpost("/api/projects", {"projectId": proj, "name": "Private Test", "createdBy": owner, "isPublic": False})
    if resp.status_code not in (201, 409):
        print("Failed to create project; aborting")
        print(resp.status_code, resp.text)
        sys.exit(2)
    else:
        print("create project result:")
        print(resp.status_code, resp.text)

    print("3) Ensure public listing does not include private project")
    r = rget("/api/projects")
    if r.status_code == 200:
        projects = r.json()
        names = [p.get("projectId") for p in projects]
        print("public projects:", names)
        if proj in names:
            print("ERROR: private project visible in public list")
            sys.exit(3)

    print("4) Non-member cannot access project details")
    expect(rget(f"/api/projects/{proj}", params={"userId": user}), 403)

    print("5) Non-member cannot join private project")
    expect(rpost(f"/api/projects/{proj}/join", {"userId": user}), 403)

    print("6) Owner invites the user")
    expect(rpost(f"/api/projects/{proj}/invite", {"requestingUser": owner, "inviteUser": user}), 200)

    print("7) Invited user can access the project now")
    expect(rget(f"/api/projects/{proj}", params={"userId": user}), 200)

    print("8) Members endpoint shows both users")
    m = rget(f"/api/projects/{proj}/members", params={"userId": user})
    if m.status_code == 200:
        print(m.json())
    else:
        print("Failed to list members", m.status_code, m.text)

    print("9) Non-owner cannot change visibility")
    expect(requests.patch(BASE + f"/api/projects/{proj}/visibility", json={"userId": user, "isPublic": True}), 403)

    print("10) Owner sets project public")
    expect(requests.patch(BASE + f"/api/projects/{proj}/visibility", json={"userId": owner, "isPublic": True}), 200)

    print("11) New user can signup and join public project")
    expect(rpost("/api/signup", {"userId": user2, "password": "pw"}), 201)
    expect(rpost(f"/api/projects/{proj}/join", {"userId": user2}), 200)

    print("All checks run. Inspect outputs above for any failures.")

if __name__ == '__main__':
    main()
