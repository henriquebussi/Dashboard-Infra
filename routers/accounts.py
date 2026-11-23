"""Administrator access to local dashboard accounts."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator
from email_validator import validate_email

from schemas import UserRBACContext, UserRole
from security import require_role
from services.accounts import DEFAULT_ACCOUNTS, list_accounts, save_account

router = APIRouter(dependencies=[Depends(require_role(UserRole.INFRA_ADMIN))])


class AccountInput(BaseModel):
    email: str = Field(max_length=254)
    role: UserRole
    password: SecretStr | None = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        email = value.strip().lower()
        if email in dict(DEFAULT_ACCOUNTS):
            return email
        return validate_email(email, check_deliverability=False).normalized


@router.get("/accounts")
def get_accounts():
    return list_accounts()


@router.post("/accounts", status_code=201)
def create_account(config: AccountInput, admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN))):
    return write_account(config, admin)


@router.put("/accounts/{original}")
def update_account(original: str, config: AccountInput,
                   admin: UserRBACContext = Depends(require_role(UserRole.INFRA_ADMIN))):
    return write_account(config, admin, original)


def write_account(config: AccountInput, admin: UserRBACContext, original: str | None = None):
    password = config.password.get_secret_value() if config.password is not None else None
    if password is not None and not 8 <= len(password) <= 256:
        raise HTTPException(422, "A senha deve ter entre 8 e 256 caracteres")
    try:
        return save_account(config.email, config.role, password, admin.user_id, original)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
