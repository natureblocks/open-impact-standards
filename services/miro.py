import json
import requests


class MiroBoard:
    def __init__(self, board_id=None):
        self.board_id = board_id
        self.access_token = json.load(open("tokens.json"))["access_token"]

    def create(self, board_name):
        url = "https://api.miro.com/v2/boards"

        payload = {
            "name": board_name,
            "policy": {
                "permissionsPolicy": {
                    "collaborationToolsStartAccess": "all_editors",
                    "copyAccess": "anyone",
                    "sharingAccess": "team_members_with_editing_rights",
                },
                "sharingPolicy": {
                    "access": "private",
                    "inviteToAccountAndBoardLinkAccess": "no_access",
                    "organizationAccess": "private",
                    "teamAccess": "private",
                },
            },
        }

        self.board_id = self._miro_api_request(url, payload)

    def create_shape(
        self,
        shape_type="rectangle",
        content="",  # text to display
        fill_color="#ffffff",
        x=0,  # x coordinate from centre of board
        y=0,  # y coordinate from centre of board
    ):
        self._check_board_id()

        url = f"https://api.miro.com/v2/boards/{self.board_id}/shapes"

        content_length = len(content)
        payload = {
            "data": {"shape": shape_type, "content": content},
            "style": {
                "borderColor": "#000000",
                "borderStyle": "normal",
                "fillColor": fill_color,
                "textAlign": "center",
                "textAlignVertical": "middle",
            },
            "position": {"origin": "center", "x": x, "y": y},
            "geometry": {
                "width": 100 if content_length < 36 else 150,
                "height": 100 if content_length < 36 else 120,
            },
        }

        return self._miro_api_request(url, payload)

    def create_invisible_shape(
        self,
        x=0,  # x coordinate from centre of board
        y=0,  # y coordinate from centre of board
    ):
        self._check_board_id()

        url = f"https://api.miro.com/v2/boards/{self.board_id}/shapes"

        payload = {
            "data": {"shape": "circle"},
            "style": {
                "fillOpacity": "0",
                "borderWidth": "1",
                "borderOpacity": "0",
                "color": "#ffffff",
            },
            "position": {"origin": "center", "x": x, "y": y},
            "geometry": {
                "width": 8,
                "height": 8,
            },
        }

        return self._miro_api_request(url, payload)

    def create_connector(
        self, from_id, to_id, end_stroke_cap="arrow", end_position_obj=None
    ):
        self._check_board_id()

        url = f"https://api.miro.com/v2/boards/{self.board_id}/connectors"

        payload = {
            "startItem": {"id": from_id, "snapTo": "left"},
            "endItem": {"id": to_id, "snapTo": "right"},
            "style": {"endStrokeCap": end_stroke_cap, "strokeWidth": "2"},
            "shape": "curved",
        }

        if end_position_obj is not None:
            del payload["endItem"]["snapTo"]
            payload["endItem"]["position"] = end_position_obj

        return self._miro_api_request(url, payload)

    def delete_shape(self, shape_id):
        self._check_board_id()

        url = f"https://api.miro.com/v2/boards/{self.board_id}/shapes/{shape_id}"

        return self._miro_api_request(url, None, request_type="DELETE")

    def _miro_api_request(self, url, payload, request_type="POST"):
        headers = {
            "accept": "application/json",
            "authorization": "Bearer " + self.access_token,
        }

        if request_type == "POST":
            headers["content-type"] = "application/json"
            response = json.loads(
                requests.post(url, json=payload, headers=headers).text
            )
        elif request_type == "DELETE":
            response = json.loads(requests.delete(url, headers=headers).text)

        if "type" in response and response["type"] == "error":
            raise Exception(response["message"])

        return response["id"]

    def _check_board_id(self):
        if self.board_id is None:
            raise Exception("Cannot create shape: board_id is None")
