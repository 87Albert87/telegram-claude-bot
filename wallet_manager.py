"""
Wallet Manager — Secure wallet handling for DeFi trading.
Supports Base and BNB chains. Private keys encrypted with Fernet at rest.
"""

import logging
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from eth_account import Account
from config import BASE_RPC_URL, BNB_RPC_URL

logger = logging.getLogger(__name__)

CHAINS = {
    "base": {
        "rpc_url": BASE_RPC_URL,
        "chain_id": 8453,
        "name": "Base",
        "explorer": "https://basescan.org",
        "native_token": "ETH",
        "wrapped_native": "0x4200000000000000000000000000000000000006",
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    },
    "bnb": {
        "rpc_url": BNB_RPC_URL,
        "chain_id": 56,
        "name": "BNB Chain",
        "explorer": "https://bscscan.com",
        "native_token": "BNB",
        "wrapped_native": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",
        "usdc": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",
    },
}

ERC20_ABI = [
    {"constant": True, "inputs": [{"name": "_owner", "type": "address"}],
     "name": "balanceOf", "outputs": [{"name": "", "type": "uint256"}],
     "type": "function"},
    {"constant": True, "inputs": [], "name": "decimals",
     "outputs": [{"name": "", "type": "uint8"}], "type": "function"},
    {"constant": True, "inputs": [], "name": "symbol",
     "outputs": [{"name": "", "type": "string"}], "type": "function"},
    {"constant": False,
     "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
     "name": "approve", "outputs": [{"name": "", "type": "bool"}], "type": "function"},
    {"constant": True,
     "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
     "name": "allowance", "outputs": [{"name": "", "type": "uint256"}], "type": "function"},
]


def get_w3(chain: str) -> Web3:
    cfg = CHAINS[chain]
    w3 = Web3(Web3.HTTPProvider(cfg["rpc_url"]))
    if chain == "bnb":
        w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    return w3


def validate_private_key(private_key: str) -> tuple[bool, str]:
    try:
        key = private_key.strip()
        if not key.startswith("0x"):
            key = "0x" + key
        account = Account.from_key(key)
        return True, account.address
    except Exception as e:
        return False, str(e)


def get_native_balance(chain: str, address: str) -> dict:
    w3 = get_w3(chain)
    balance = w3.eth.get_balance(Web3.to_checksum_address(address))
    return {
        "balance_wei": balance,
        "balance_human": float(Web3.from_wei(balance, "ether")),
        "symbol": CHAINS[chain]["native_token"],
    }


def get_token_balance(chain: str, address: str, token_address: str) -> dict:
    w3 = get_w3(chain)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address), abi=ERC20_ABI
    )
    balance = contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
    decimals = contract.functions.decimals().call()
    try:
        symbol = contract.functions.symbol().call()
    except Exception:
        symbol = token_address[:8]
    return {
        "balance_raw": balance,
        "balance_human": balance / (10 ** decimals),
        "symbol": symbol,
        "decimals": decimals,
    }


def get_full_balances(chain: str, address: str, token_list: list[str] = None) -> dict:
    native = get_native_balance(chain, address)
    tokens = {}
    check_tokens = token_list or [CHAINS[chain]["usdc"]]
    for tok in check_tokens:
        try:
            tokens[tok] = get_token_balance(chain, address, tok)
        except Exception as e:
            logger.warning(f"Failed to get balance for {tok}: {e}")
    return {"native": native, "tokens": tokens}


def approve_token(chain: str, private_key: str, token_address: str,
                  spender: str, amount: int) -> str:
    w3 = get_w3(chain)
    account = Account.from_key(private_key)
    contract = w3.eth.contract(
        address=Web3.to_checksum_address(token_address), abi=ERC20_ABI
    )
    tx = contract.functions.approve(
        Web3.to_checksum_address(spender), amount
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gasPrice": w3.eth.gas_price,
        "chainId": CHAINS[chain]["chain_id"],
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()


def send_transaction(chain: str, private_key: str, tx_data: dict) -> str:
    w3 = get_w3(chain)
    account = Account.from_key(private_key)
    tx = {
        "from": account.address,
        "to": Web3.to_checksum_address(tx_data["to"]),
        "data": tx_data.get("data", "0x"),
        "value": int(tx_data.get("value", 0)),
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": int(tx_data.get("gasLimit", tx_data.get("gas", 300000))),
        "gasPrice": int(tx_data.get("gasPrice", w3.eth.gas_price)),
        "chainId": CHAINS[chain]["chain_id"],
    }
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()


def wait_for_receipt(chain: str, tx_hash: str, timeout: int = 120) -> dict:
    w3 = get_w3(chain)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
    return {
        "status": "success" if receipt["status"] == 1 else "failed",
        "gas_used": receipt["gasUsed"],
        "block_number": receipt["blockNumber"],
        "tx_hash": tx_hash,
    }


def estimate_gas_cost_usd(chain: str, gas_estimate: int, native_price_usd: float) -> float:
    w3 = get_w3(chain)
    gas_price_wei = w3.eth.gas_price
    gas_cost_native = float(Web3.from_wei(gas_price_wei * gas_estimate, "ether"))
    return gas_cost_native * native_price_usd
