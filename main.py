import aiofiles
import asyncio
import requests
import gzip
import json
from typing import List

class BusNotifier:
    def __init__(self, api_url: str, bus_id: str, target_stop: str, direction: str, notify_distance: int, time_threshold: int):
        self.api_url = api_url
        self.bus_id = bus_id
        self.target_stop = target_stop
        self.direction = direction
        self.notify_distance = notify_distance
        self.time_threshold = time_threshold
        self.stop_event = asyncio.Event()  # 初始化 asyncio.Event

    async def get_route_id(self, line_to_route_path: str) -> str:
        
        # 根據 bus_id 獲取對應的 route_id
        async with aiofiles.open(line_to_route_path, 'r', encoding='utf-8') as f:
            data_route = json.loads(await f.read())
        return str(data_route.get(self.bus_id, ''))

    async def get_stop_id(self, route_id: str) -> str:

        # 查找目標站牌之id
        stop_url = "https://tcgbusfs.blob.core.windows.net/blobbus/GetStop.gz"
        response = requests.get(stop_url)
        gzflieSaveName = "stop.gz"
        with open(gzflieSaveName, 'wb') as f:
            f.write(response.content)

        with gzip.open(gzflieSaveName, 'r') as f:
            jdata = f.read()
        data = json.loads(jdata)

        for d in data['BusInfo']:
            if d['nameZh'] == self.target_stop and d['goBack'] == self.direction and d['routeId'] == int(route_id):
                return d['Id']
        return None

    async def get_stop_list(self, route_id: str, route_to_stop_path: str) -> List[int]:
        
        # 根據 route_id 獲取所有站牌編號
        async with aiofiles.open(route_to_stop_path, 'r', encoding='utf-8') as f:
            data_stop = json.loads(await f.read())
        return data_stop.get(route_id, [])

    async def get_bus_data(self, route_id: str) -> List[dict]:
        
        # 獲取指定路線的公車實時位置資訊
        response = requests.get(self.api_url)
        gzflieSaveName = "temp.gz"
        with open(gzflieSaveName, 'wb') as f:
            f.write(response.content)

        with gzip.open(gzflieSaveName, 'r') as f:
            jdata = f.read()
        data = json.loads(jdata)

        datum = [datum for datum in data['BusInfo'] if datum['RouteID'] == int(route_id)]

        if response.status_code == 200:
            return datum
        else:
            raise Exception("Failed to fetch bus data")

    async def check_bus_positions(self, route_id: str, Tstop_id: str, stop_list: List[int]) -> None:
        """
        檢查公車位置並發送通知
        """
        stops = await self.get_bus_data(route_id)
        error_dict = {-1: '尚未發車', -2: '交管不停靠', -3: '末班車已過', -4: '今日未營運'}

        while int(Tstop_id) - self.notify_distance not in stop_list:
            self.notify_distance -= 1
            if self.notify_distance < 0:
                await self.stop_event.set() 
                return

        for stop in stops:
            stop_id = stop['StopID']
            if stop_id == int(Tstop_id) - self.notify_distance:
                arrive_time = int(stop['EstimateTime'])
                if arrive_time < self.time_threshold and arrive_time > 0:
                    await self.notify_user()
                    self.stop_event.set()  
                    return
                elif arrive_time < 0:
                    print(self.bus_id + error_dict.get(arrive_time, 'Unknown error'))
                    if arrive_time in (-2, -3):
                        self.notify_distance -= 1
                        if self.notify_distance < 0:
                            self.stop_event.set()
                    elif arrive_time == -4:
                        self.stop_event.set()                        
                    return
                else:
                    print("Please Wait")
                    return

    async def notify_user(self) -> None:
        """
        通知用戶公車接近目標站點
        """
        print(f"Bus {self.bus_id} is approaching {self.target_stop} in the next {self.notify_distance} stops!")

    async def run(self, line_to_route_path: str, route_to_stop_path: str) -> None:
        """
        執行查詢和通知流程
        """
        route_id = await self.get_route_id(line_to_route_path)
        if not route_id:
            print(f"Route ID for bus {self.bus_id} not found.")
            return

        Tstop_id = await self.get_stop_id(route_id)
        if not Tstop_id:
            print(f"Target Stop ID for bus {self.bus_id} not found.")
            return

        stop_list = await self.get_stop_list(route_id, route_to_stop_path)

        while not self.stop_event.is_set():
            await self.check_bus_positions(route_id, Tstop_id, stop_list)
            await asyncio.sleep(60)  # 每分鐘檢查一次

async def main():
    # 模擬用戶資訊
    user_configs = [
        {'bus_id': '672', 'target_stop': '博仁醫院', 'direction': '1', 'notify_distance': 5, 'time_threshold': 100},
        {'bus_id': '615', 'target_stop': '新莊高中', 'direction': '0', 'notify_distance': 3, 'time_threshold': 150},
        {'bus_id': '508區', 'target_stop': '永明派出所', 'direction': '1', 'notify_distance': 4, 'time_threshold': 120},
        {'bus_id': '重慶幹線', 'target_stop': '捷運芝山站(戲曲中心)', 'direction': '1', 'notify_distance': 2, 'time_threshold': 130},
    ]

    # 模擬多個用戶同時操作
    tasks = []
    for config in user_configs:
        notifier = BusNotifier(
            api_url='https://tcgbusfs.blob.core.windows.net/blobbus/GetEstimateTime.gz',
            bus_id=config['bus_id'],
            target_stop=config['target_stop'],
            direction=config['direction'],
            notify_distance=config['notify_distance'],
            time_threshold=config['time_threshold']
        )
        tasks.append(notifier.run('./Line_to_Route.json', './Route_to_Stop.json'))

    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
