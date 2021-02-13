# Copyright 2020 Richard Koshak
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Communicator that publishes and subscribes to openHAB's REST API.
Classes:
    - openhab_rest: publishes state updates to openHAB Items.
"""
import json
import traceback
from threading import Thread
import requests
import sseclient
from core.connection import Connection

class OpenhabREST(Connection):
    """Publishes a state to a given openHAB Item. Expects there to be a URL
    parameter set to the base URL of the openHAB instance. Subscribes to the OH
    SSE feed for commands on the registered Items.
    """

    def __init__(self, msg_processor, params):
        """Starts the SSE subscription and registers for commands on
        RefreshItem. Expects the following params:
        - "URL": base URL of the openHAB instance NOTE: does not support TLS.
        - "RefreshItem": Name of the openHAB Item that, when it receives a
        command will cause sensor_reporter to publish the most recent states of
        all the sensors.
        - msg_processor: message handler for command to the RefreshItem
        """
        super().__init__(msg_processor, params)
        self.log.info("Initializing openHAB REST Connection...")

        self.openhab_url = params("URL")
        self.refresh_item = params("RefreshItem")
        self.registered[self.refresh_item] = msg_processor

        # Subscribe to SSE events and start processing the events
        stream = requests.get("{}/rest/events".format(self.openhab_url),
                              stream=True)
        self.client = sseclient.SSEClient(stream)

        self.thread = Thread(target=self._get_messages)
        self.thread.start()
        self.stop = False

    def _get_messages(self):
        """Blocks until stop is set to True. Loops through all the events on the
        SSE subscription and if it's a command to a registered Item, call's that
        Item's handler.
        """
        for event in self.client.events():
            # If we are stopping exit.
            if self.stop:
                return

            # See if this is an event we care about. Commands on registered Items.
            decoded = json.loads(event.data)
            if decoded["type"] == "ItemCommandEvent":
                item = decoded["topic"].replace("smarthome/items/", "").replace("/command", "")
                if item in self.registered:
                    payload = json.loads(decoded["payload"])
                    msg = payload["value"]
                    self.log.info("Received command from %s: %s", item, msg)
                    self.registered[item](msg)

    def publish(self, state, item):
        """Publishes the passed in state to the passed in Item as an update."""
        try:
            self.log.debug("Publishing message %s to %s", state, item)
            response = requests.post("{}/rest/items/{}"
                                    .format(self.openhab_url, item),
                                    data=state, timeout=10)
            response.raise_for_status()
        except ConnectionError:
            self.log.error("Failed to connect to %s\n%s", self.openhab_url,
                           traceback.format_exc())
        except requests.exceptions.Timeout:
            self.log.error("Timed out connecting to %s")
        except requests.exceptions.HTTPError as ex:
            self.log.error("Received and unsuccessful response code %s", ex)

    def disconnect(self):
        """Stops the event processing loop."""
        self.log.info("Disconnecting from openHAB SSE")
        self.stop = True
        self.thread.join()
