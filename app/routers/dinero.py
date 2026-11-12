from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/dinero", tags=["dinero"])


@router.get("")
def dinero_home() -> RedirectResponse:
    """Mi dinero ya no es una página: los traspasos están en Hoy y las cuentas en Mi patrimonio."""
    return RedirectResponse("/patrimonio#cuentas", status_code=302)
