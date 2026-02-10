"""
DeFi Trading Agent — Core trading logic.

Integrates:
- Velvet Capital API (portfolio management, rebalance)
- Honeypot.is API (token safety)
- CoinGecko (via web_tools, for price data)
- web3.py (on-chain execution via wallet_manager)

Safety rules:
- Max 25% of portfolio per trade (risk-adjusted down)
- Honeypot + liquidity check before every trade
- Slippage protection (max 2%, dynamic)
- Gas cost must be < 5% of trade value
- Risk score 0-100; skip >70
- Confirmation required for trades > TRADE_AUTO_THRESHOLD
"""

import json
import logging
import httpx
from datetime import datetime, timezone

from config import (
    TRADE_AUTO_THRESHOLD, MAX_POSITION_PCT,
    MAX_SLIPPAGE_BPS, ADMIN_IDS,
)

logger = logging.getLogger(__name__)

VELVET_PORTFOLIO_URL = "https://api.velvet.capital/api/v3/portfolio/owner"
VELVET_REBALANCE_URL = "https://eventsapi.velvetdao.xyz/api/v3/rebalance"
VELVET_REBALANCE_TXN_URL = "https://eventsapi.velvetdao.xyz/api/v3/rebalance/txn"
VELVET_DEPOSIT_URL = "https://eventsapi.velvetdao.xyz/api/v3/portfolio/deposit"
VELVET_WITHDRAW_URL = "https://eventsapi.velvetdao.xyz/api/v3/portfolio/withdraw"
HONEYPOT_API_URL = "https://api.honeypot.is/v2/IsHoneypot"

CHAIN_IDS = {"base": 8453, "bnb": 56}


# =============================================================================
# Token Safety Checker
# =============================================================================

async def check_token_safety(token_address: str, chain: str = "base") -> dict:
    chain_id = CHAIN_IDS.get(chain, 8453)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(HONEYPOT_API_URL, params={
                "address": token_address,
                "chainID": chain_id,
            })
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Honeypot API error: {e}")
        return {
            "safe": False, "risk_score": 100,
            "is_honeypot": False, "buy_tax": 0, "sell_tax": 0,
            "holder_count": 0, "is_open_source": False, "liquidity_usd": 0,
            "warnings": [f"Safety check failed: {e}"], "risk_level": "unknown",
        }

    honeypot_result = data.get("honeypotResult", {})
    simulation = data.get("simulationResult", {})
    summary = data.get("summary", {})
    token_info = data.get("token", {})
    pair_info = data.get("pair", {})
    contract = data.get("contractCode", {})

    is_honeypot = honeypot_result.get("isHoneypot", False)
    buy_tax = simulation.get("buyTax", 0)
    sell_tax = simulation.get("sellTax", 0)
    risk_level = summary.get("riskLevel", "unknown")

    risk_score = 0
    warnings = []

    if is_honeypot:
        risk_score = 100
        warnings.append("HONEYPOT DETECTED")

    if sell_tax > 10:
        risk_score = max(risk_score, 80)
        warnings.append(f"High sell tax: {sell_tax}%")
    elif sell_tax > 5:
        risk_score = max(risk_score, 50)
        warnings.append(f"Moderate sell tax: {sell_tax}%")

    if buy_tax > 10:
        risk_score = max(risk_score, 70)
        warnings.append(f"High buy tax: {buy_tax}%")

    liquidity = float(pair_info.get("liquidity", 0))
    if liquidity < 1000:
        risk_score = max(risk_score, 90)
        warnings.append(f"Very low liquidity: ${liquidity:.0f}")
    elif liquidity < 10000:
        risk_score = max(risk_score, 60)
        warnings.append(f"Low liquidity: ${liquidity:.0f}")

    is_open_source = contract.get("openSource", False)
    if not is_open_source:
        risk_score = max(risk_score, 40)
        warnings.append("Contract not verified/open-source")

    holder_count = token_info.get("totalHolders", 0)
    if holder_count < 50:
        risk_score = max(risk_score, 55)
        warnings.append(f"Very few holders: {holder_count}")

    return {
        "safe": risk_score < 70 and not is_honeypot,
        "risk_score": min(risk_score, 100),
        "is_honeypot": is_honeypot,
        "buy_tax": buy_tax,
        "sell_tax": sell_tax,
        "holder_count": holder_count,
        "is_open_source": is_open_source,
        "liquidity_usd": liquidity,
        "warnings": warnings,
        "risk_level": risk_level,
    }


async def analyze_token(token_address: str, chain: str = "base") -> str:
    safety = await check_token_safety(token_address, chain)
    result = f"Token Safety Report for {token_address} ({chain}):\n"
    result += f"Safe: {'YES' if safety['safe'] else 'NO'}\n"
    result += f"Risk Score: {safety['risk_score']}/100\n"
    result += f"Risk Level: {safety['risk_level']}\n"
    result += f"Honeypot: {'YES - DO NOT TRADE' if safety['is_honeypot'] else 'No'}\n"
    result += f"Buy Tax: {safety['buy_tax']}%\n"
    result += f"Sell Tax: {safety['sell_tax']}%\n"
    result += f"Holders: {safety['holder_count']}\n"
    result += f"Verified: {'Yes' if safety['is_open_source'] else 'No'}\n"
    result += f"Liquidity: ${safety['liquidity_usd']:,.0f}\n"
    if safety["warnings"]:
        result += f"Warnings: {', '.join(safety['warnings'])}\n"
    return result


# =============================================================================
# Velvet Capital Client
# =============================================================================

async def get_velvet_portfolios(wallet_address: str, chain: str = "base") -> list:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{VELVET_PORTFOLIO_URL}/{wallet_address}",
                params={"chain": chain},
            )
            resp.raise_for_status()
            data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])
    except Exception as e:
        logger.error(f"Velvet portfolio fetch error: {e}")
        return []


async def velvet_rebalance_txn(rebalance_address: str, sell_token: str,
                                buy_token: str, sell_amount: str,
                                remaining_tokens: list, owner: str,
                                slippage: str = "100") -> dict:
    payload = {
        "rebalanceAddress": rebalance_address,
        "sellToken": sell_token,
        "buyToken": buy_token,
        "sellAmount": sell_amount,
        "slippage": slippage,
        "remainingTokens": remaining_tokens,
        "owner": owner,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(VELVET_REBALANCE_TXN_URL, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Velvet rebalance txn error: {e}")
        return {"error": str(e)}


async def velvet_deposit(portfolio: str, deposit_amount: str,
                          deposit_token: str, user: str) -> dict:
    payload = {
        "portfolio": portfolio,
        "depositAmount": deposit_amount,
        "depositToken": deposit_token,
        "user": user,
        "depositType": "batch",
        "tokenType": "erc20",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(VELVET_DEPOSIT_URL, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Velvet deposit error: {e}")
        return {"error": str(e)}


async def velvet_withdraw(portfolio: str, withdraw_amount: str,
                           withdraw_token: str, user: str) -> dict:
    payload = {
        "portfolio": portfolio,
        "withdrawAmount": withdraw_amount,
        "withdrawToken": withdraw_token,
        "user": user,
        "withdrawType": "batch",
        "tokenType": "erc20",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(VELVET_WITHDRAW_URL, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Velvet withdraw error: {e}")
        return {"error": str(e)}


# =============================================================================
# Trade Planning & Risk Management
# =============================================================================

def calculate_position_size(portfolio_value_usd: float, risk_score: int,
                             max_pct: float = None) -> float:
    max_pct = max_pct or MAX_POSITION_PCT
    if risk_score < 20:
        pct = max_pct
    elif risk_score < 40:
        pct = max_pct * 0.6
    elif risk_score < 60:
        pct = max_pct * 0.3
    else:
        pct = max_pct * 0.1
    return portfolio_value_usd * (pct / 100)


def calculate_dynamic_slippage(liquidity_usd: float, trade_size_usd: float) -> int:
    if liquidity_usd <= 0:
        return MAX_SLIPPAGE_BPS
    impact = trade_size_usd / liquidity_usd
    if impact < 0.001:
        return 50
    elif impact < 0.01:
        return 100
    elif impact < 0.05:
        return 150
    else:
        return MAX_SLIPPAGE_BPS


def split_trade(total_amount: float, max_per_trade: float) -> list[float]:
    if total_amount <= max_per_trade:
        return [total_amount]
    parts = []
    remaining = total_amount
    while remaining > 0:
        chunk = min(remaining, max_per_trade)
        parts.append(round(chunk, 2))
        remaining -= chunk
    return parts


def _parse_price_from_result(price_result: str) -> float:
    for line in price_result.split("\n"):
        if line.startswith("Price:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return float(parts[1])
                except ValueError:
                    pass
    return 0.0


async def plan_trade(chain: str, token_in: str, token_out: str,
                      amount_usd: str, wallet_address: str,
                      portfolio_value_usd: float) -> dict:
    # 1. Safety check on buy token
    safety = await check_token_safety(token_out, chain)
    if not safety["safe"]:
        return {
            "approved": False,
            "reason": f"Token failed safety check (risk: {safety['risk_score']}/100). "
                      f"Warnings: {', '.join(safety['warnings'])}",
            "safety": safety,
        }

    # 2. Position sizing
    trade_usd = float(amount_usd)
    max_position = calculate_position_size(portfolio_value_usd, safety["risk_score"])
    capped_reason = None
    if trade_usd > max_position:
        trade_usd = max_position
        capped_reason = f"Position capped at ${max_position:.2f} ({MAX_POSITION_PCT}% rule, risk-adjusted)"

    # 3. Dynamic slippage
    slippage_bps = calculate_dynamic_slippage(safety["liquidity_usd"], trade_usd)

    # 4. Gas estimation
    from wallet_manager import estimate_gas_cost_usd
    from web_tools import get_crypto_price
    native_coin = "ethereum" if chain == "base" else "binancecoin"
    try:
        price_str = await get_crypto_price(native_coin)
        native_price = _parse_price_from_result(price_str)
    except Exception:
        native_price = 3000 if chain == "base" else 600
    gas_cost = estimate_gas_cost_usd(chain, 300000, native_price)

    if gas_cost > trade_usd * 0.05:
        return {
            "approved": False,
            "reason": f"Gas cost (${gas_cost:.2f}) exceeds 5% of trade value (${trade_usd:.2f})",
            "gas_cost_usd": gas_cost,
        }

    # 5. Split into chunks
    max_chunk = max_position * 0.5
    chunks = split_trade(trade_usd, max_chunk)

    # 6. Determine if auto-execute or needs confirmation
    needs_confirmation = trade_usd >= TRADE_AUTO_THRESHOLD

    return {
        "approved": True,
        "chain": chain,
        "token_in": token_in,
        "token_out": token_out,
        "amount_usd": round(trade_usd, 2),
        "original_amount": float(amount_usd),
        "capped_reason": capped_reason,
        "slippage_bps": slippage_bps,
        "gas_cost_usd": round(gas_cost, 4),
        "risk_score": safety["risk_score"],
        "safety": safety,
        "chunks": chunks,
        "needs_confirmation": needs_confirmation,
        "wallet": wallet_address,
    }


# =============================================================================
# Trade Execution
# =============================================================================

async def execute_trade(trade_id: int, user_id: int) -> str:
    from storage import get_wallet, get_trade, update_trade
    from wallet_manager import send_transaction, wait_for_receipt, CHAINS

    trade = get_trade(trade_id)
    if not trade:
        return f"Trade {trade_id} not found."
    if trade["user_id"] != user_id:
        return "Unauthorized."
    if trade["status"] not in ("confirmed", "pending"):
        return f"Trade already {trade['status']}."

    chain = trade["chain"]
    wallet = get_wallet(user_id, chain)
    if not wallet:
        return f"No wallet connected for {chain}. Use /connect_wallet."

    update_trade(trade_id, status="executing")

    try:
        slippage = str(trade.get("slippage_bps", 100))

        # Execute via Velvet Capital
        portfolios = await get_velvet_portfolios(wallet["address"], chain)

        if not portfolios:
            update_trade(trade_id, status="failed", error="No Velvet Capital portfolio found")
            return (
                "No Velvet Capital portfolio found for this wallet. "
                "Create a portfolio at dapp.velvet.capital first."
            )

        portfolio = portfolios[0]
        rebalance_addr = portfolio.get("rebalancing", portfolio.get("rebalanceAddress", ""))

        if not rebalance_addr:
            update_trade(trade_id, status="failed", error="No rebalance address in portfolio")
            return "Velvet portfolio has no rebalance address. Check your portfolio setup."

        txn_data = await velvet_rebalance_txn(
            rebalance_address=rebalance_addr,
            sell_token=trade["token_in"],
            buy_token=trade["token_out"],
            sell_amount=trade["amount_in"],
            remaining_tokens=[],
            owner=wallet["address"],
            slippage=slippage,
        )

        if "error" in txn_data:
            error = txn_data["error"]
            update_trade(trade_id, status="failed", error=str(error))
            return f"Trade failed: {error}"

        tx = txn_data.get("tx", txn_data)
        if "to" not in tx:
            update_trade(trade_id, status="failed", error="No transaction data returned")
            return "Trade failed: API did not return valid transaction data."

        tx_hash = send_transaction(chain, wallet["private_key"], tx)
        update_trade(trade_id, tx_hash=tx_hash)

        receipt = wait_for_receipt(chain, tx_hash)

        if receipt["status"] == "success":
            update_trade(trade_id, status="completed",
                        executed_at=datetime.now(tz=timezone.utc).isoformat())
            explorer = CHAINS[chain]["explorer"]
            return (
                f"Trade executed successfully!\n"
                f"TX: {explorer}/tx/{tx_hash}\n"
                f"Gas used: {receipt['gas_used']}"
            )
        else:
            update_trade(trade_id, status="failed", error="Transaction reverted on-chain")
            return f"Trade reverted on-chain. TX: {tx_hash}"

    except Exception as e:
        logger.error(f"Trade execution error: {e}", exc_info=True)
        update_trade(trade_id, status="failed", error=str(e))
        return f"Trade execution failed: {e}"


# =============================================================================
# Goal-Based Trading
# =============================================================================

async def create_trading_goal(user_id: int, target_amount: float,
                               chain: str = "base") -> str:
    from storage import save_trading_goal, get_wallet
    from wallet_manager import get_full_balances

    wallet = get_wallet(user_id, chain)
    if not wallet:
        return f"No wallet connected for {chain}. Use /connect_wallet first."

    balances = get_full_balances(chain, wallet["address"])
    native_bal = balances["native"]["balance_human"]

    strategy = {
        "target_usd": target_amount,
        "initial_portfolio": {
            "native": native_bal,
            "tokens": {
                addr: info["balance_human"]
                for addr, info in balances["tokens"].items()
            },
        },
        "risk_allocation": {
            "low_risk": 0.6,
            "med_risk": 0.3,
            "high_risk": 0.1,
        },
        "status": "analyzing",
    }

    goal_id = save_trading_goal(user_id, target_amount, chain, json.dumps(strategy))

    return (
        f"Trading goal created (ID: {goal_id})\n"
        f"Target: +${target_amount:.2f}\n"
        f"Chain: {chain}\n"
        f"Wallet: {wallet['address'][:8]}...{wallet['address'][-6:]}\n"
        f"Portfolio: {native_bal:.4f} {balances['native']['symbol']}\n\n"
        f"Strategy: 60% low-risk, 30% medium-risk, 10% high-risk allocation.\n"
        f"Each trade requires safety checks and your confirmation above ${TRADE_AUTO_THRESHOLD}."
    )


# =============================================================================
# Portfolio & History
# =============================================================================

async def get_portfolio_summary(user_id: int, chain: str = "base") -> str:
    from storage import get_wallet
    from wallet_manager import get_full_balances, CHAINS

    wallet = get_wallet(user_id, chain)
    if not wallet:
        return f"No wallet connected for {chain}. Use /connect_wallet."

    address = wallet["address"]
    balances = get_full_balances(chain, address)

    result = f"Portfolio Summary ({CHAINS[chain]['name']}):\n"
    result += f"Wallet: {address[:8]}...{address[-6:]}\n\n"

    native = balances["native"]
    result += f"{native['symbol']}: {native['balance_human']:.6f}\n"

    for addr, info in balances["tokens"].items():
        if info["balance_human"] > 0:
            result += f"{info['symbol']}: {info['balance_human']:.6f}\n"

    portfolios = await get_velvet_portfolios(address, chain)
    if portfolios:
        result += f"\nVelvet Capital Portfolios: {len(portfolios)}\n"
        for p in portfolios:
            name = p.get("name", p.get("portfolioName", "Unnamed"))
            pid = p.get("portfolioId", p.get("id", "N/A"))
            result += f"- {name} (ID: {pid})\n"
    else:
        result += "\nNo Velvet Capital portfolios found.\n"

    return result


async def get_trade_history(user_id: int, limit: int = 10) -> str:
    from storage import get_trades
    trades = get_trades(user_id, limit)

    if not trades:
        return "No trades recorded yet."

    result = f"Trade History (last {len(trades)}):\n\n"
    for t in trades:
        status_icon = {
            "completed": "[OK]", "failed": "[FAIL]", "executing": "[...]",
            "pending": "[WAIT]", "confirmed": "[CONF]", "rejected": "[REJ]",
        }.get(t["status"], "[?]")

        tin = t["token_in_symbol"] or t["token_in"][:10]
        tout = t["token_out_symbol"] or t["token_out"][:10]
        result += f"{status_icon} {tin} -> {tout}\n"
        result += f"  Amount: {t['amount_in']} | Chain: {t['chain']}\n"
        if t["tx_hash"]:
            result += f"  TX: {t['tx_hash'][:16]}...\n"
        if t["error"]:
            result += f"  Error: {t['error'][:100]}\n"
        result += f"  {t['created_at'][:19]}\n\n"

    return result
