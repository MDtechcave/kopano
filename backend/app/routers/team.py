"""Managing the sales team. ADMINISTRATORS ONLY.

Sales staff cannot add or invite colleagues. An administrator creates each account,
gets a temporary password to hand over, and can deactivate someone at any time.
A deactivated person is locked out on their very next request, even mid-session.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ROLE_SALES, User, get_db
from app.schemas import TeamMemberCreate, TeamMemberCreated, TeamMemberOut, TeamMemberUpdate
from app.security import generate_temporary_password, hash_password, require_admin

router = APIRouter(prefix="/api/team", tags=["team (admin)"])


def find_staff_or_404(db: Session, user_id: int) -> User:
    person = db.get(User, user_id)
    if person is None or person.role != ROLE_SALES:
        raise HTTPException(404, "Team member not found.")
    return person


def created_view(person: User, temporary_password: str) -> TeamMemberCreated:
    return TeamMemberCreated(**TeamMemberOut.model_validate(person).model_dump(), temporary_password=temporary_password)


@router.get("", response_model=list[TeamMemberOut])
def list_team(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(User).where(User.role == ROLE_SALES).order_by(User.is_active.desc(), User.full_name)
    return db.scalars(query).all()


@router.post("", response_model=TeamMemberCreated, status_code=status.HTTP_201_CREATED)
def add_team_member(data: TeamMemberCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Someone with this email already has an account.")

    temporary_password = generate_temporary_password()
    person = User(
        email=data.email,
        full_name=data.full_name,
        password_hash=hash_password(temporary_password),
        role=ROLE_SALES,
        is_admin=False,  # nobody can be made an administrator through the API
        must_change_password=True,
        added_by_name=admin.full_name,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    # The password is shown this once. Only its hash is stored.
    return created_view(person, temporary_password)


@router.patch("/{user_id}", response_model=TeamMemberOut)
def set_active(user_id: int, data: TeamMemberUpdate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Deactivate or reactivate a salesperson."""
    person = find_staff_or_404(db, user_id)
    if person.id == admin.id:
        raise HTTPException(409, "You cannot deactivate your own account.")
    if person.is_admin:
        raise HTTPException(403, "Administrator accounts cannot be changed from here.")
    person.is_active = data.is_active
    db.commit()
    db.refresh(person)
    return person


@router.post("/{user_id}/reset-password", response_model=TeamMemberCreated)
def reset_password(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """For a forgotten password: a new temporary one, which must be changed at next sign-in."""
    person = find_staff_or_404(db, user_id)
    if person.id == admin.id or person.is_admin:
        raise HTTPException(403, "Administrator passwords cannot be reset from here.")
    temporary_password = generate_temporary_password()
    person.password_hash = hash_password(temporary_password)
    person.must_change_password = True
    db.commit()
    db.refresh(person)
    return created_view(person, temporary_password)
