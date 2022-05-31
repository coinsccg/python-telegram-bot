# -*- coding: utf-8 -*-
import asyncio
import json
import math
import time
import re

import requests
import web3.eth

import constant
from web3 import Web3
from telebot.async_telebot import AsyncTeleBot
from web3.middleware import geth_poa_middleware
from telebot.asyncio_filters import TextMatchFilter, TextFilter, IsReplyFilter
from telebot import types,formatting

API_TOKEN = '5142526572:AAEpRiuZ7tQV5ma6Lv0HyBFy8seSfj8V7Ww'
bot = AsyncTeleBot(API_TOKEN)


@bot.message_handler(text=TextFilter(starts_with="0x", ignore_case=True))
async def products_command_handler(message: types.Message):
    addr = message.text.split(" ")[-1]
    try:
        st = SearchToken()
        start_time = time.time()
        result = await st.search(addr)
        end_time = time.time()
        print(end_time - start_time)
        text = f"""
名字：{result["name"]}   符号：{result["symbol"]}
精度：{result["decimals"]}    总量：{result["total_supply"]}
价格：{result["price"]}{" BNB" if result["is_bnb"] else " USDT"}
所有权：0x{result["owner"][-4:]}{" √已放弃" if (result["owner"][-4:].lower() == "0000") or (result["owner"][-4:].lower() == "dead") else " ×未放弃"} 
BNB现价: ${result["bnb_price"]}
池子流动性：{result["liquidity"]} {"WBNB" if result["is_bnb"] else "USDT"}
买Gas：${result["buy"]}    卖Gas：${result["sell"]}
交易开关：{"有" if result["is_trade"] else "无"}    手续费：{"有" if result["is_fee"] else "无"}
增发开关：{"有" if result["is_mint"] else "无"}    杀区块：{"有" if result["is_block"] else "无"}
假丢权限：{"无" if result["is_authority"] else "有"}    黑名单：{"有" if result["is_blacklist"] else "无"}
限购开关：{"有" if result["is_limit_buy"] else "无"}    池子：{result["pool_rate"]}%
调整税率：{"有" if result["is_fee_adj"] else "无"}    销毁：{result["burn_rate"]}%
        """
    except Exception as e:
        print(e)
        text = "😕 contract address error"

    await bot.send_message(message.chat.id, formatting.format_text(
        formatting.hcode(text)
    ), parse_mode="HTML")
    # await bot.send_message(message.chat.id, '<p>Downloading your photo...</p>', parse_mode='HTML',
    #                        disable_web_page_preview=True)

def run():
    bot.add_custom_filter(TextMatchFilter())
    bot.add_custom_filter(IsReplyFilter())
    asyncio.run(bot.polling())


class SearchToken:
    bsc_rpc = "https://bsc-dataseed1.binance.org/"
    eth_rpc = "https://kovan.infura.io/v3/457c1ac43c544b05abfef0163084a7a6"
    bsc_usdt = "0x55d398326f99059fF775485246999027B3197955"
    bsc_wbnb = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    null_address = "0x000000000000000000000000000000000000dEaD"
    pancakeswap_factory = "0xcA143Ce32Fe78f1f7019d7d551a6402fC5350c73"

    def __init__(self):
        self.w3 = Web3(Web3.HTTPProvider(self.bsc_rpc))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

    async def get_pair(self, token0: str, token1: str) -> str:
        with open("abi/pancakeswap_factory_abi.json", "r", encoding="UTF-8") as f:
            content = f.read()
        factory_abi = json.loads(content)
        contract = self.w3.eth.contract(Web3.toChecksumAddress(self.pancakeswap_factory), abi=factory_abi)
        pair = contract.functions.getPair(Web3.toChecksumAddress(token0), Web3.toChecksumAddress(token1)).call()
        return pair

    async def get_reserves(self, pair: str) -> (int, int, str):
        with open("abi/pancakeswap_pair_abi.json", "r", encoding="UTF-8") as f:
            content = f.read()
        pair_abi = json.loads(content)
        contract = self.w3.eth.contract(Web3.toChecksumAddress(pair), abi=pair_abi)
        reserves = contract.functions.getReserves().call()
        token0 = contract.functions.token0().call()
        return reserves[0], reserves[1], token0

    @staticmethod
    async def get_contract_abi(token: str) -> [dict]:
        result = requests.get(
            url=constant.BSC_CONTRACT_ABI_API.format(
                token))  # 使用代理时报错时降级urllib3,不能使用1.26.0。解决方案： pip install urllib3==1.25.11
        abi = json.loads(result.json()["result"])
        return abi

    @staticmethod
    async def get_source_code(token: str) -> (str, str):
        resp = requests.get(url=constant.BSC_CONTRACT_SOURCE_CODE_API.format(token))
        result = resp.json()["result"][0]
        source_code = result["SourceCode"]
        proxy_contract = result["Implementation"]
        return source_code, proxy_contract

    @staticmethod
    async def get_bnb_price():
        resp = requests.get(url=constant.BSC_BNB_LAST_PRICE_API)
        return resp.json()["result"]["ethusd"]

    @staticmethod
    async def get_name(contract: web3.eth.Contract) -> str:
        return contract.functions.name().call()

    @staticmethod
    async def get_symbol(contract: web3.eth.Contract) -> str:
        return contract.functions.symbol().call()

    @staticmethod
    async def get_decimals(contract: web3.eth.Contract) -> int:
        return contract.functions.decimals().call()

    @staticmethod
    async def get_total_supply(contract: web3.eth.Contract) -> int:
        try:
            total_supply = contract.functions.totalSupply().call()
        except:
            total_supply = 0
        return total_supply

    @staticmethod
    async def get_balance_of(contract: web3.eth.Contract, address: str) -> int:
        try:
            balance = contract.functions.balanceOf(address).call()
        except:
            balance = 0
        return balance

    @staticmethod
    async def check_any(source: str) -> (bool, bool, bool, bool, bool, bool, bool):
        is_mint = False
        if source.find("function mint", 0, -1) > -1:
            is_mint = True

        # 查询是否杀区块
        is_block = False
        if source.find("block.number", 0, -1) > -1:
            is_block = True

        # 是否有黑名单
        is_blacklist = False
        pattern = re.compile('require\(!(.*)\[sender\]', re.I)
        if len(pattern.findall(source)) > 0:
            is_blacklist = True

        # 是否有手续费
        is_fee = False
        if source.find("createPair", 0, -1) > -1:
            is_fee = True

        # 是否丢假权限
        is_authority = False
        if source.find("_owner", 0, -1) and source.find("function owner() public view returns (address) {\r\n        return _owner;\r\n    }", 0, -1) > -1:
            is_authority = True

        # 限购开关
        is_limit_buy = False
        if source.find("require(amount <=", 0, -1) > -1:
            is_limit_buy = True

        # 交易开关
        is_trade = False
        pattern = re.compile('require\(!([a-zA-Z]+),', re.I)
        if len(pattern.findall(source)) > 0:
            is_trade = True

        # 调整税率开关
        is_fee_adj = False
        pattern = re.compile('([a-zA-Z_]+)fee = ([a-zA-Z]+);', re.I)
        if len(pattern.findall(source)) > 0:
            is_fee_adj = True

        return is_mint, is_block, is_blacklist, is_fee, is_authority, is_limit_buy, is_trade, is_fee_adj

    @staticmethod
    async def get_erc20_transfer_gas(contract: str, address: str) -> (int, int):

        buy: int = 0
        sell: int = 0
        n = 1
        while True:
            resp = requests.get(url=constant.BSC_ERC20_TRANSFER_API.format(contract, address, n))
            result = resp.json()["result"]
            for i in result:
                # 卖
                if Web3.toChecksumAddress(i["to"]) == Web3.toChecksumAddress(address):
                    gas_price = resp.json()["result"][0]["gasPrice"]
                    gas_used = resp.json()["result"][0]["gasUsed"]
                    sell = int(gas_price) * int(gas_used)
                # 卖
                if Web3.toChecksumAddress(i["from"]) == Web3.toChecksumAddress(address):
                    gas_price = resp.json()["result"][0]["gasPrice"]
                    gas_used = resp.json()["result"][0]["gasUsed"]
                    buy = int(gas_price) * int(gas_used)

                if buy > 0 and sell > 0:
                    break

            if buy > 0 and sell > 0:
                break

            if len(result) < 10:
                break
            n += 1

        return buy, sell

    async def search(self, token: str) -> dict:
        if not Web3.isAddress(token):
            raise Exception("address error")
        # 查询abi
        source, proxy_contract = await self.get_source_code(token)

        is_mint, is_block, is_blacklist, is_fee, is_authority, is_limit_buy, is_trade, is_fee_adj = await self.check_any(str(source))

        abi: str
        if len(proxy_contract) > 0:
            abi = await self.get_contract_abi(proxy_contract)
        else:
            abi = await self.get_contract_abi(token)

        contract = self.w3.eth.contract(Web3.toChecksumAddress(token), abi=abi)

        owner: str
        price: float
        liquidity: float
        is_bnb: bool

        # 获取pair地址
        try:
            owner = contract.functions.owner().call()
        except:
            try:
                owner = contract.functions.getOwner().call()
            except:
                owner = "0x000000000000000000000000000000000000dEaD"

        # 异步查询usdt和bnb pair
        res = await asyncio.gather(self.get_pair(token, self.bsc_usdt), self.get_pair(token, self.bsc_wbnb))
        usdt_pair = res[0]
        bnb_pair = res[1]

        try:
            usdt_pair_balance = contract.functions.balanceOf(usdt_pair).call()
            bnb_pair_balance = contract.functions.balanceOf(bnb_pair).call()
        except:
            usdt_pair_balance = 0
            bnb_pair_balance = 0
        if usdt_pair_balance >= bnb_pair_balance:
            pair = usdt_pair
            is_bnb = False
            pool_amount = usdt_pair_balance
        else:
            pair = bnb_pair
            is_bnb = True
            pool_amount = bnb_pair_balance

        # 异步查询bnb最新价格和token0、token1储备量
        res = await asyncio.gather(self.get_bnb_price(), self.get_reserves(pair),
                                   self.get_erc20_transfer_gas(token, pair))

        bnb_price = res[0]

        reserve0, reserve1, token0 = res[1]

        buy, sell = res[2]

        # 异步查询name、symbol、decimals、total_supply、burn
        res = await asyncio.gather(self.get_name(contract), self.get_symbol(contract), self.get_decimals(contract),
                                   self.get_total_supply(contract), self.get_balance_of(contract, self.null_address))
        name, symbol, decimals, total_supply, burn_amount = res[0], res[1], res[2], res[3], res[4]

        if Web3.toChecksumAddress(token) == Web3.toChecksumAddress(token0):
            liquidity = float(Web3.fromWei(reserve1, "ether"))
            reserve0 = reserve0 / math.pow(10, decimals)
            if reserve0 > 0:
                price = round(liquidity / reserve0, 6)
            else:
                price = 0
        else:
            liquidity = float(Web3.fromWei(reserve0, "ether"))
            reserve1 = reserve1 / math.pow(10, decimals)
            if reserve1 > 0:
                price = round(liquidity / reserve1, 6)
            else:
                price = 0

        if total_supply > 0:
            burn_rate = round(burn_amount * 100 / total_supply, 2)
            pool_rate = round(pool_amount * 100 / total_supply, 2)
            print(pool_amount, total_supply)
        else:
            burn_rate = 0
            pool_rate = 0

        return {
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "owner": owner,
            "pair": pair,
            "price": round(price, 8),
            "total_supply": round(total_supply / math.pow(10, decimals)),
            "bnb_price": bnb_price,
            "liquidity": round(liquidity, 2),
            "is_bnb": is_bnb,
            "is_mint": is_mint,
            "is_block": is_block,
            "is_blacklist": is_blacklist,
            "is_fee": is_fee,
            "burn_rate": burn_rate,
            "is_authority": is_authority,
            "is_limit_buy": is_limit_buy,
            "is_fee_adj": is_fee_adj,
            "is_trade": is_trade,
            "pool_rate": pool_rate,
            "sell": round(float(Web3.fromWei(sell, "ether")) * float(bnb_price) / 6.68, 4),
            "buy": round(float(Web3.fromWei(buy, "ether")) * float(bnb_price) / 6.68, 4)
        }


if __name__ == '__main__':
    print("telegram bot running...")
    run()
