# -*- coding: utf-8 -*-
import asyncio
import json
import math
import time

import requests
import web3.eth

import constant
from web3 import Web3
from telebot.async_telebot import AsyncTeleBot
from web3.middleware import geth_poa_middleware
from telebot.asyncio_filters import TextMatchFilter, TextFilter, IsReplyFilter
from telebot import types

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
合约：{addr}
名字：{result["name"]}
符号：{result["symbol"]}
精度：{result["decimals"]}
总供应量：{result["total_supply"]}
价格：{result["price"]}{" BNB" if result["is_bnb"] else " USDT"}
所有权：{result["owner"]}
{"BNB" if result["is_bnb"] else "USDT"}池地址：{result["pair"]}
池子流动性：{result["liquidity"]} {"BNB" if result["is_bnb"] else "USDT"}
BNB现价: ${result["bnb_price"]}
买gas: {result["buy"]} BNB    卖gas: {result["sell"]} BNB
增发开关：{"有" if result["is_mint"] else "无"}    销毁占比：{result["burn_rate"]}%
        """
    except Exception as e:
        print(e)
        text = "😕 contract address error"

    await bot.reply_to(message, text=text)


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
        return contract.functions.totalSupply().call()

    @staticmethod
    async def get_balance_of(contract: web3.eth.Contract, address: str) -> int:
        return contract.functions.balanceOf(address).call()

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

        is_mint = False
        if str(source).find("function mint", 0, -1) > -1:
            is_mint = True

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

        usdt_pair_balance = contract.functions.balanceOf(usdt_pair).call()
        bnb_pair_balance = contract.functions.balanceOf(bnb_pair).call()

        if usdt_pair_balance >= bnb_pair_balance:
            pair = usdt_pair
            is_bnb = False
        else:
            pair = bnb_pair
            is_bnb = True

        # 异步查询bnb最新价格和token0、token1储备量
        res = await asyncio.gather(self.get_bnb_price(), self.get_reserves(pair), self.get_erc20_transfer_gas(token, pair))

        bnb_price = res[0]

        reserve0, reserve1, token0 = res[1]

        buy, sell = res[2]

        # 异步查询name、symbol、decimals、total_supply、burn
        res = await asyncio.gather(self.get_name(contract), self.get_symbol(contract), self.get_decimals(contract),
                                   self.get_total_supply(contract), self.get_balance_of(contract, self.null_address))
        name, symbol, decimals, total_supply, burn_amount = res[0], res[1], res[2], res[3], res[4]

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
            "price": round(price, 6),
            "total_supply": round(total_supply / math.pow(10, decimals)),
            "bnb_price": bnb_price,
            "liquidity": round(liquidity, 2),
            "is_bnb": is_bnb,
            "is_mint": is_mint,
            "burn_rate": round(burn_amount * 100 / total_supply, 4),
            "sell": round(Web3.fromWei(sell, "ether"), 6),
            "buy": round(Web3.fromWei(buy, "ether"), 6)
        }


if __name__ == '__main__':
    print("telegram bot running...")
    run()
