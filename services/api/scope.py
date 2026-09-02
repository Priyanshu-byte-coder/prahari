"""Who can see what ([C10]), expressed once and applied everywhere.

The rule this module exists to enforce: **hiding a button is not access control.** Every read
goes through a predicate built here, so a Transport viewer who guesses the URL of a Police
camera gets an empty list rather than a rendering bug.

A Scope is what a JWT becomes. It carries the department, the district and the role, and it is
computed once per request (or once per socket, in D5) - never re-derived from a query parameter,
because a scope the client can influence is not a scope.

[C10]'s matrix, in one place:

    role                 live   detections  wl read  wl write  route      export  admin
    Viewer (dept)        own    own         -        -         -          -       -
    Operator             own    own         own      -         own        -       -
    Investigator         all    all         all      own       statewide  yes     -
    Dept Admin           own    own         own      own       own        yes     users in dept
    System Admin         -      -           -        -         -          -       config + audit

The last row is deliberate and worth saying out loud: the most privileged account in the system
cannot watch video. Administering a surveillance system and using one are different jobs, and an
admin account that can do both is the one an insider abuses.
"""

from dataclasses import dataclass

VIEWER = "VIEWER"
OPERATOR = "OPERATOR"
INVESTIGATOR = "INVESTIGATOR"
DEPT_ADMIN = "DEPT_ADMIN"
SYSTEM_ADMIN = "SYSTEM_ADMIN"

ROLES = {VIEWER, OPERATOR, INVESTIGATOR, DEPT_ADMIN, SYSTEM_ADMIN}

# Capability -> the roles that hold it. Read this table against [C10]; nothing else in the
# codebase gets to have an opinion about who may do what.
CAPABILITIES = {
    "live":        {VIEWER, OPERATOR, INVESTIGATOR, DEPT_ADMIN},
    "detections":  {VIEWER, OPERATOR, INVESTIGATOR, DEPT_ADMIN},
    "watchlist:read":  {OPERATOR, INVESTIGATOR, DEPT_ADMIN},
    "watchlist:write": {INVESTIGATOR, DEPT_ADMIN},
    "alerts:read":  {OPERATOR, INVESTIGATOR, DEPT_ADMIN},
    "alerts:write": {OPERATOR, INVESTIGATOR, DEPT_ADMIN},
    "route":        {OPERATOR, INVESTIGATOR, DEPT_ADMIN},
    "export":       {INVESTIGATOR, DEPT_ADMIN},
    "admin:users":  {DEPT_ADMIN},
    "admin:config": {SYSTEM_ADMIN},
    "admin:audit":  {SYSTEM_ADMIN},
}

# Roles whose reads are not confined to their own department.
STATEWIDE = {INVESTIGATOR}


@dataclass(frozen=True)
class Scope:
    user_id: str = None
    role: str = None
    dept_id: int = None
    district_code: str = None

    # -- capabilities -------------------------------------------------------------------

    @property
    def normalised_role(self):
        return (self.role or "").upper()

    def can(self, capability):
        return self.normalised_role in CAPABILITIES.get(capability, set())

    @property
    def statewide(self):
        return self.normalised_role in STATEWIDE

    # -- the predicate every repository uses --------------------------------------------

    def department_filter(self):
        """Parameters for the `(%(all_departments)s OR owner_dept_id = ANY(%(departments)s))`
        predicate that every scoped query carries.

        A statewide role passes all_departments=True; everyone else gets exactly their own
        department, and a user with no department gets an empty array - which matches nothing.
        That is the right default: a misconfigured account should see nothing, not everything.
        """
        if self.statewide:
            return {"all_departments": True, "departments": []}
        return {"all_departments": False,
                "departments": [self.dept_id] if self.dept_id is not None else []}

    def allows_department(self, owner_dept_id):
        if self.statewide:
            return True
        return owner_dept_id is not None and owner_dept_id == self.dept_id

    def allows_camera(self, owner_dept_id, district_code=None):
        """Cameras get a district fallback: G1 seeds them before D7 assigns departments, and a
        camera with neither is withheld rather than shown."""
        if self.normalised_role == SYSTEM_ADMIN:
            return False                       # [C10]: config and audit only, never video
        if self.statewide:
            return True
        if self.dept_id is not None and owner_dept_id is not None:
            return self.dept_id == owner_dept_id
        if self.district_code and district_code:
            return self.district_code == district_code
        return False


# The predicate itself, so no caller writes it twice.
DEPARTMENT_PREDICATE = "(%(all_departments)s OR owner_dept_id = ANY(%(departments)s))"


def apply_session_scope(cur, scope):
    """Set the Postgres session variables the RLS policies read.

    RLS is the backstop, not the primary control: the application predicate above is what runs
    first. The point of the backstop is that a query somebody forgets to scope still cannot
    return another department's rows.
    """
    cur.execute("SELECT set_config('prahari.statewide', %s, true)",
                ("on" if scope.statewide else "off",))
    departments = scope.department_filter()["departments"]
    cur.execute("SELECT set_config('prahari.dept_ids', %s, true)",
                (",".join(str(d) for d in departments),))
