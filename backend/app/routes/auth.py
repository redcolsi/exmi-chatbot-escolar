"""
Endpoints de autenticación:
  POST /auth/login          → devuelve token JWT
  POST /auth/logout         → invalidación del lado del cliente
  POST /auth/change-password → cambiar contraseña del usuario
  GET  /auth/me             → perfil del usuario autenticado
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.models.models import User
from app.schemas.schemas import LoginRequest, Token, ChangePasswordRequest, UpdateAccountRequest, MessageResponse
from app.auth.security import verify_password, hash_password, create_access_token, require_user

router = APIRouter(prefix="/auth", tags=["Autenticación"])


@router.post("/login", response_model=Token)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        User.email == request.email,
        User.is_active == True,
    ).first()

    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Correo o contraseña incorrectos.",
        )

    token = create_access_token({"sub": user.email, "role": user.role})
    return Token(access_token=token, role=user.role, username=user.username)


@router.post("/logout", response_model=MessageResponse)
def logout(current_user: User = Depends(require_user)):
    # JWT es sin estado: el cliente elimina el token
    return MessageResponse(message="Sesión cerrada correctamente.")


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta.")
    if request.new_password != request.confirm_password:
        raise HTTPException(status_code=400, detail="Las contraseñas nuevas no coinciden.")
    if len(request.new_password) < 6:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres.")

    current_user.hashed_password = hash_password(request.new_password)
    db.commit()
    return MessageResponse(message="Contraseña actualizada correctamente.")


@router.put("/account", response_model=Token)
def update_account(
    request: UpdateAccountRequest,
    current_user: User = Depends(require_user),
    db: Session = Depends(get_db),
):
    """Actualiza el correo y username del usuario autenticado.

    Requiere la contraseña actual y conserva el rol. Como el JWT usa el
    correo como subject, se emite un token nuevo después del cambio.
    """
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta.")

    email = request.email.strip().lower()
    username = request.username.strip()

    if not email or "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=400, detail="Ingresa un correo electrónico válido.")
    if len(email) > 255:
        raise HTTPException(status_code=400, detail="El correo es demasiado largo.")
    if not username or len(username) < 3:
        raise HTTPException(status_code=400, detail="El username debe tener al menos 3 caracteres.")
    if len(username) > 100:
        raise HTTPException(status_code=400, detail="El username es demasiado largo.")

    other_email = db.query(User).filter(
        User.email == email, User.id != current_user.id
    ).first()
    if other_email:
        raise HTTPException(status_code=409, detail="Ese correo ya está registrado.")

    other_username = db.query(User).filter(
        User.username == username, User.id != current_user.id
    ).first()
    if other_username:
        raise HTTPException(status_code=409, detail="Ese username ya está registrado.")

    current_user.email = email
    current_user.username = username
    current_user.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(current_user)

    token = create_access_token({"sub": current_user.email, "role": current_user.role})
    return Token(access_token=token, role=current_user.role, username=current_user.username)


@router.get("/me")
def get_me(current_user: User = Depends(require_user)):
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "role": current_user.role,
    }
