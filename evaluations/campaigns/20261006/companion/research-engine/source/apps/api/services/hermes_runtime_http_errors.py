"""Public route-selection failures without exposing operator configuration."""
from fastapi.responses import JSONResponse

from services.hermes_client import HermesRuntimeSelectionError


def public_error(error: HermesRuntimeSelectionError):
    code = str(error)
    if code in {'hermes_runtime_request_override_forbidden', 'openshell_canary_session_not_authorized',
                'openshell_canary_company_not_authorized'}:
        return 403, {'detail': '当前请求未获准使用所选运行环境，请核对访问权限。',
                     'error_code': 'runtime_access_denied', 'retryable': False}
    if code == 'openshell_canary_company_context_required':
        return 400, {'detail': '请先选择本次分析的公司资料范围。',
                     'error_code': 'runtime_scope_required', 'retryable': False}
    return 503, {'detail': '运行环境尚未就绪，请联系管理员核对配置与接入状态。',
                 'error_code': 'runtime_selection_unavailable', 'retryable': False}


async def handle(_request, error: HermesRuntimeSelectionError):
    status, body = public_error(error)
    return JSONResponse(status_code=status, content=body, headers={'Cache-Control': 'no-store'})
