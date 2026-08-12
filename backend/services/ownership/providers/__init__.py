"""
The provider table: SourceKind -> the thing that can populate it.

Registration is explicit rather than discovered by scanning the package, so a
half-finished provider dropped into this directory cannot start answering for
entities before it is ready. An entity naming a kind that is absent here is
logged and skipped, which is how a phase can ship its registry rows before its
provider exists.
"""

from services.ownership.providers.base import (
    EntityConfig,
    OwnershipProvider,
    ProviderResult,
)
from services.ownership.providers.coingecko_treasury import CoinGeckoTreasuryProvider
from services.ownership.providers.manual import ManualProvider
from services.ownership.providers.onchain_wallet import OnChainWalletProvider
from services.ownership.providers.sec_13f import Sec13FProvider
from services.ownership.providers.sec_form4 import SecForm4Provider

PROVIDERS: dict[str, OwnershipProvider] = {
    CoinGeckoTreasuryProvider.kind: CoinGeckoTreasuryProvider(),
    ManualProvider.kind: ManualProvider(),
    OnChainWalletProvider.kind: OnChainWalletProvider(),
    Sec13FProvider.kind: Sec13FProvider(),
    SecForm4Provider.kind: SecForm4Provider(),
}

__all__ = ["PROVIDERS", "EntityConfig", "OwnershipProvider", "ProviderResult"]
