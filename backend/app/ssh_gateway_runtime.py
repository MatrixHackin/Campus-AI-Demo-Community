from app.core.config import get_settings
from app.services.ssh_gateway_service import SSHGatewayService

settings = get_settings()
ssh_gateway_service = SSHGatewayService(settings=settings)
