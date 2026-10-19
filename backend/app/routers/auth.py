"""Create an account and sign in."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ROLE_CLIENT, Company, User, get_db, utc_now
from app.schemas import (
    AccountUpdate,
    ChangePassword,
    ForgotPasswordOut,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenOut,
    UserOut,
)
from app.security import (
    check_password,
    create_token,
    generate_temporary_password,
    get_current_user,
    get_signed_in_user,
    hash_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
def register(data: RegisterRequest, db: Session = Depends(get_db)):
    already_exists = db.scalar(select(User).where(User.email == data.email))
    if already_exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists.")

    # The role is set here, by us, and never taken from the request. Registering always
    # starts a NEW company account: you cannot join someone else's company by typing its
    # name, because that would let a stranger read their quotations.
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        full_name=data.full_name,
        role=ROLE_CLIENT,
        company_account=Company(name=data.company),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenOut(access_token=create_token(user), user=user)


@router.post("/login", response_model=TokenOut)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))

    # Same message for "no such user" and "wrong password" so nobody can
    # use this form to find out which emails have accounts.
    if user is None or not check_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")

    # Only said AFTER the password is right, so it cannot be used to discover accounts.
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been deactivated. Please contact your administrator.")

    user.last_login_at = utc_now()
    db.commit()
    return TokenOut(access_token=create_token(user), user=user)


@router.get("/me", response_model=UserOut)
def who_am_i(user: User = Depends(get_signed_in_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_account(data: AccountUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Change your own name or phone. Email, company and role cannot be changed here."""
    if data.full_name is not None:
        user.full_name = data.full_name
    if data.phone is not None:
        user.phone = data.phone
    db.commit()
    db.refresh(user)
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(data: ChangePassword, user: User = Depends(get_signed_in_user), db: Session = Depends(get_db)):
    if not check_password(data.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Your current password is not correct.")
    if data.new_password == data.current_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Choose a password you have not used just now.")
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    db.commit()


@router.post("/forgot-password", response_model=ForgotPasswordOut)
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    temporary_password = generate_temporary_password()

    if user is not None:
        user.password_hash = hash_password(temporary_password)
        user.must_change_password = True
        db.commit()
        db.refresh(user)
        return ForgotPasswordOut(
            message="Use the temporary password below to sign in, then choose a new one.",
            temporary_password=temporary_password,
        )

    return ForgotPasswordOut(
        message="If an account exists for that email address, a temporary password has been generated.",
        temporary_password=temporary_password,
    )
