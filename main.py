# -*- coding: utf-8 -*-
import asyncio
import json
import math
import requests
import constant
from web3 import Web3
from telebot.async_telebot import AsyncTeleBot
from web3.middleware import geth_poa_middleware
from telebot import types, TeleBot

API_TOKEN = '5142526572:AAEpRiuZ7tQV5ma6Lv0HyBFy8seSfj8V7Ww'
bot = AsyncTeleBot(API_TOKEN)


@bot.message_handler(commands=['bsc'])
async def products_command_handler(message: types.Message):
    addr = message.text.split(" ")[-1]
    try:
        st = SearchToken()
        result = await st.search(addr)
        text = f"""
合约：{addr}
名字：{result["name"]}
符号：{result["symbol"]}
精度：{result["decimals"]}
总供应量：{result["total_supply"]}
价格：{result["price"]}/{"BNB" if result["is_bnb"] else "USDT"}
合约所有者：{result["owner"]}
{"BNB" if result["is_bnb"] else "USDT"}池地址：{result["pair"]}
池子流动性：{result["liquidity"]} {"BNB" if result["is_bnb"] else "USDT"}
BNB现价: ${result["bnb_price"]}
        """
    except:
        text = "contract address error"

    await bot.reply_to(message, text=text)


def run():
    asyncio.run(bot.polling())


class SearchToken:
    bsc_rpc = "https://bsc-dataseed1.binance.org/"
    eth_rpc = "https://kovan.infura.io/v3/457c1ac43c544b05abfef0163084a7a6"
    bsc_usdt = "0x55d398326f99059fF775485246999027B3197955"
    bsc_wbnb = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
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

    async def search(self, token: str) -> dict:
        if not Web3.isAddress(token):
            raise Exception("address error")
        # 查询abi
        _, proxy_contract = await self.get_source_code(token)
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
                owner = "0x000000000000000000000000000000000000dead"

        usdt_pair = await self.get_pair(token, self.bsc_usdt)
        bnb_pair = await self.get_pair(token, self.bsc_wbnb)

        usdt_pair_balance = contract.functions.balanceOf(usdt_pair).call()
        bnb_pair_balance = contract.functions.balanceOf(bnb_pair).call()

        if usdt_pair_balance >= bnb_pair_balance:
            pair = usdt_pair
            is_bnb = False
        else:
            pair = bnb_pair
            is_bnb = True

        # 查询bnb最新价格
        bnb_price = await self.get_bnb_price()

        # 获取token0和token1储备量
        reserve0, reserve1, token0 = await self.get_reserves(pair)

        # 查询name
        name = contract.functions.name().call()

        # 查询symbol
        symbol = contract.functions.symbol().call()

        # 查询token1精度
        decimals = contract.functions.decimals().call()

        # 查询总供应量
        total_supply = contract.functions.totalSupply().call()

        if Web3.toChecksumAddress(token) == Web3.toChecksumAddress(token0):
            liquidity = float(Web3.fromWei(reserve1, "ether"))
            price = round(liquidity / (reserve0 / math.pow(10, decimals)), 6)
        else:
            liquidity = float(Web3.fromWei(reserve0, "ether"))
            price = round(liquidity / (reserve1 / math.pow(10, decimals)), 6)
        return {
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "owner": owner,
            "pair": pair,
            "price": price,
            "total_supply": round(total_supply / math.pow(10, decimals), 6),
            "bnb_price": bnb_price,
            "liquidity": liquidity,
            "is_bnb": is_bnb
        }


if __name__ == '__main__':
    print("telegram bot running...")
    run()


