import asyncio
import base64
import json
import queue
import threading
import time
from typing import Any

import cv2
import rtmaps.types
import websockets
from rtmaps.base_component import BaseComponent


# ------------------------------------------------------------------
# Image encoding configuration
# ------------------------------------------------------------------

# Images wider than this value are resized while preserving
# their aspect ratio.
DEFAULT_IMAGE_MAX_WIDTH = 640

# JPEG quality from 1 to 100.
DEFAULT_JPEG_QUALITY = 70

# Maximum number of encoded frames waiting to be transmitted.
DEFAULT_QUEUE_SIZE = 30

# Maximum WebSocket message size.
WEBSOCKET_MAX_SIZE = 16 * 1024 * 1024

# Object used to stop the asynchronous sender cleanly.
_STOP_MARKER = object()


class rtmaps_python(BaseComponent):
    def __init__(self):
        BaseComponent.__init__(self)

        self._loop = None
        self._thread = None

        self._stopping = False
        self._uri = ""

        # Latest optional state received through json_data.
        self._latest_state: dict[str, Any] = {}
        self._state_lock = threading.Lock()

        # Queue containing one complete JSON payload per frame.
        self._frame_queue: queue.Queue[Any] = queue.Queue(
            maxsize=DEFAULT_QUEUE_SIZE
        )

        self._frame_number = 0
        self._started_at = 0.0

        # Diagnostics.
        self._frames_received = 0
        self._frames_encoded = 0
        self._frames_queued = 0
        self._frames_sent = 0
        self._encoding_failures = 0

    def Dynamic(self):
        # Optional input containing additional JSON state.
        # The camera works even when json_data isn't connected.
        self.add_input(
            "json_data",
            rtmaps.types.AUTO,
        )

        # Connect the image output of the RTMaps camera component here.
        self.add_input(
            "camera_image",
            rtmaps.types.AUTO,
        )

        # Address reached by this RTMaps machine.
        #
        # When using an SSH tunnel, keep 127.0.0.1.
        # Without a tunnel, use a directly reachable Hyades address.
        self.add_property(
            "ip_address",
            "127.0.0.1",
            rtmaps.types.AUTO,
        )

        # RTMaps input port of rtmaps_bridge_server.py.
        self.add_property(
            "port",
            4545,
            rtmaps.types.AUTO,
        )

        self.add_property(
            "image_max_width",
            DEFAULT_IMAGE_MAX_WIDTH,
            rtmaps.types.AUTO,
        )

        self.add_property(
            "jpeg_quality",
            DEFAULT_JPEG_QUALITY,
            rtmaps.types.AUTO,
        )

        self.add_property(
            "queue_size",
            DEFAULT_QUEUE_SIZE,
            rtmaps.types.AUTO,
        )

        # True when the Hyades bridge sends one ACK per accepted frame.
        self.add_property(
            "wait_for_ack",
            True,
            rtmaps.types.AUTO,
        )

    def Birth(self):
        ip_address = str(
            self.properties["ip_address"].data
        )

        port = int(
            self.properties["port"].data
        )

        queue_size = int(
            self.properties["queue_size"].data
        )

        if queue_size < 1:
            raise ValueError(
                "queue_size must be at least 1"
            )

        jpeg_quality = int(
            self.properties["jpeg_quality"].data
        )

        if not 1 <= jpeg_quality <= 100:
            raise ValueError(
                "jpeg_quality must be between 1 and 100"
            )

        image_max_width = int(
            self.properties["image_max_width"].data
        )

        if image_max_width < 1:
            raise ValueError(
                "image_max_width must be positive"
            )

        self._uri = (
            f"ws://{ip_address}:{port}/socket"
        )

        self._stopping = False
        self._latest_state = {}

        self._frame_queue = queue.Queue(
            maxsize=queue_size
        )

        self._frame_number = 0
        self._started_at = time.perf_counter()

        self._frames_received = 0
        self._frames_encoded = 0
        self._frames_queued = 0
        self._frames_sent = 0
        self._encoding_failures = 0

        self._loop = asyncio.new_event_loop()

        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="rtmaps-websocket-sender",
            daemon=True,
        )

        self._thread.start()

        print(
            "RTMaps WebSocket sender started: "
            f"uri={self._uri}, "
            f"queue_size={queue_size}, "
            f"jpeg_quality={jpeg_quality}, "
            f"image_max_width={image_max_width}"
        )

    def _run_event_loop(self):
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(
                self._websocket_client()
            )

        except Exception as exc:
            if not self._stopping:
                print(
                    "RTMaps WebSocket event-loop error: "
                    f"{exc}"
                )

        finally:
            pending_tasks = asyncio.all_tasks(
                self._loop
            )

            for task in pending_tasks:
                task.cancel()

            if pending_tasks:
                self._loop.run_until_complete(
                    asyncio.gather(
                        *pending_tasks,
                   *    return_exceptions=True,
      *             )
                )

*   async def _get_next_payload(sel*):
        return await asyncio.to*thread(
            self._frame_qu*ue.get
        )

    async def _s*nd_control_message(
        self,
*       websocket,
        payload:*dict[str, Any],
    ):
        awa*t websocket.send(
            json*dumps(
                payload,
  *             separators=(",", ":")*
                ensure_ascii=Fals*,
                allow_nan=False,*            )
        )

    async*def _wait_for_ack(
        self,
 *      websocket,
        expected_*rame: int,
    ):
        response*= await websocket.recv()

        *f not isinstance(response, str):
 *          raise RuntimeError(
    *           "Expected a text ACK fr*m the Hyades bridge"
            )*
        payload = json.loads(resp*nse)

        if payload.get("type*) != "ack":
            raise Runt*meError(
                "Expected*an ACK from Hyades, "
            *   f"received: {payload}"
        *   )

        acknowledged_frame =*int(
            payload.get("fram*", -1)
        )

        if ackno*ledged_frame != expected_frame:
  *         raise RuntimeError(
     *          "Incorrect Hyades ACK: "*                f"expected={expect*d_frame}, "
                f"rece*ved={acknowledged_frame}"
        *   )

    async def _websocket_cli*nt(self):
        # If transmissio* fails after taking a frame from t*e queue,
        # keep the payloa* and retry it after reconnection.
*       pending_payload = None

   *    while not self._stopping:
    *       try:
                async *ith websockets.connect(
          *         self._uri,
              *     ping_interval=20,
           *        ping_timeout=20,
         *          max_size=WEBSOCKET_MAX_S*ZE,
                    compressio*=None,
                    open_ti*eout=10,
                ) as webs*cket:
                    print(
 *                      "RTMaps WebS*cket connected: "
                *       f"{self._uri}"
            *       )

                    awai* self._send_control_message(
     *                  websocket,
     *                  {
              *             "type": "stream_start*,
                            "sou*ce": "rtmaps-external-camera",
   *                        "live": Tr*e,
                            "fo*mat": "jpeg-base64",
             *          },
                    )*
                    while not sel*._stopping:
                      * if pending_payload is None:
     *                      pending_payl*ad = (
                           *    await self._get_next_payload()*                            )

   *                    if pending_pay*oad is _STOP_MARKER:
             *              self._frame_queue.ta*k_done()
                         *  pending_payload = None
         *                  break

         *              frame_number = int(
*                           pending*payload["frame"]
                 *      )

                        a*ait websocket.send(
              *             json.dumps(
         *                      pending_payl*ad,
                              * separators=(",", ":"),
          *                     ensure_ascii=*alse,
                            *   allow_nan=False,
              *             )
                   *    )

                        wai*_for_ack = bool(
                 *          self.properties[
                                "wait_for_ack"
                            ].*ata
                        )

   *                    if wait_for_ac*:
                            awai* self._wait_for_ack(
             *                  websocket,
     *                          expected*frame=frame_number,
              *             )

                  *     self._frames_sent += 1

     *                  # This queued fr*me has now completed
             *          # transmission.
        *               self._frame_queue.t*sk_done()
                        *ending_payload = None

           *            if self._frames_sent %*100 == 0:
                        *   print(
                        *       "RTMaps frames: "
         *                      f"received={*elf._frames_received}, "
         *                      f"encoded={s*lf._frames_encoded}, "
           *                    f"queued={self*_frames_queued}, "
               *                f"sent={self._fram*s_sent}, "
                       *        f"waiting="
              *                 f"{self._frame_qu*ue.qsize()}"
                     *      )

                    if se*f._stopping:
                     *  try:
                           *await self._send_control_message(
*                               web*ocket,
                           *    {
                            *       "type": "stream_end",
     *                              "fra*es_sent": (
                      *                 self._frames_sent*                                  * ),
                              * },
                            )
*                       except Exce*tion:
                            *ass

            except Exception *s exc:
                if not self*_stopping:
                    pri*t(
                        "RTMaps*WebSocket error: "
               *        f"{exc}. Retrying in 2 sec*nds."
                    )

     *              await asyncio.sleep(*)

        print(
            "RTM*ps WebSocket client finished"
    *   )

    def _update_json_state(s*lf):
        if not self.has_data(*json_data"):
            return

 *      raw_data = self.inputs[
            "json_data"
        ].ioelt*data

        try:
            if *asattr(raw_data, "tobytes"):
     *          raw_bytes = raw_data.tob*tes()
            elif isinstance(*aw_data, bytes):
                r*w_bytes = raw_data
            eli* isinstance(raw_data, str):
      *         raw_bytes = raw_data.enco*e("utf-8")
            else:
     *          raise TypeError(
       *            "Unsupported json_data*type: "
                    f"{typ*(raw_data).__name__}"
            *   )

            incoming_state =*json.loads(
                raw_by*es.decode("utf-8")
            )

*           if not isinstance(
    *           incoming_state,
       *        dict,
            ):
     *          raise ValueError(
      *             "json_data must conta*n a JSON object"
                )*
        except Exception as exc:
*           print(
                *Invalid RTMaps json_data input: "
*               f"{exc}"
          * )

            return

        wi*h self._state_lock:
            se*f._latest_state = incoming_state

*   def _prepare_camera_frame(self)*
        if not self.has_data("cam*ra_image"):
            return Non*

        try:
            image_e*ement = self.inputs[
                "camera_image"
            ].ioe*t.data

            frame = image_*lement.image_data

        except *xception as exc:
            print*
                "Unable to retrie*e RTMaps camera image: "
         *      f"{exc}"
            )

    *       return None

        if fra*e is None:
            print(
    *           "RTMaps camera image is*None"
            )

            r*turn None

        if not hasattr(*rame, "size") or frame.size == 0:
*           print(
                *RTMaps camera image is empty"
    *       )

            return None
*        self._frames_received += 1*
        # Make the OpenCV input c*ntiguous when needed.
        fram* = frame.copy()

        height, w*dth = frame.shape[:2]

        ima*e_max_width = int(
            sel*.properties[
                "image_max_width"
            ].data
   *    )

        if width > image_ma*_width:
            scale = (
    *           image_max_width / float*width)
            )

            *esized_width = image_max_width
   *        resized_height = max(
    *           1,
                int(*ound(height * scale)),
           *)

            frame = cv2.resize(*                frame,
           *    (
                    resized_*idth,
                    resized_*eight,
                ),
        *       interpolation=cv2.INTER_ARE*,
            )

        jpeg_qual*ty = int(
            self.propert*es[
                "jpeg_quality"
            ].data
        )

    *   successful, encoded_image = cv2*imencode(
            ".jpg",
    *       frame,
            [
                int(cv2.IMWRITE_JPEG_QUALITY),
                jpeg_quality,*            ],
        )

        *f not successful:
            self*_encoding_failures += 1

         *  print(
                "RTMaps c*uld not encode camera frame "
    *           f"{self._frames_receive*}"
            )

            retu*n None

        self._frames_encod*d += 1

        self._frame_number*+= 1

        timestamp_seconds = *
            time.perf_counter()
 *          - self._started_at
     *  )

        image_base64 = base64*b64encode(
            encoded_ima*e.tobytes()
        ).decode("asci*")

        with self._state_lock:*            payload = self._latest*state.copy()

        # These keys*deliberately overwrite any fields *ith
        # the same names in js*n_data. Camera metadata is the
   *    # source of truth for this tra*smitted frame.
        payload.upd*te(
            {
                *type": "frame",
                "f*ame": self._frame_number,
        *       "timestamp": timestamp_seco*ds,
                "camera_image_*64": image_base64,
               *"image_format": "jpeg",
          *     "image_width": int(
         *          frame.shape[1]
         *      ),
                "image_he*ght": int(
                    fra*e.shape[0]
                ),
    *       }
        )

        return*payload

    def _queue_frame(
   *    self,
        payload: dict[str, Any],
    ):
        # Blocking *s intentional when every RTMaps fr*me must
        # be preserved. If*Hyades is slower than RTMaps, this*        # applies backpressure to *he RTMaps execution path.
        *hile not self._stopping:
         *  try:
                self._frame*queue.put(
                    pay*oad,
                    timeout=0*5,
                )

            *   self._frames_queued += 1

     *          return

            exce*t queue.Full:
                prin*(
                    "RTMaps tran*mission queue is full: "
         *          f"waiting={self._frame_q*eue.qsize()}, "
                  * f"sent={self._frames_sent}"
     *          )

    def Core(self):
 *      # json_data is optional. Upd*te it whenever a new value
        # is present.
        self._update_json_state()

        # A new WebSocket message is generated only when
        # camera_image contains a new RTMaps sample.
        payload = self._prepare_camera_frame()

        if payload is None:
            return

        self._queue_frame(
            payload
        )

    def Death(self):
        print(
            "Stopping RTMaps WebSocket sender"
        )

        self._stopping = True

        # Unblock queue.get() in the network thread.
        try:
            self._frame_queue.put_nowait(
                _STOP_MARKER
            )

        except queue.Full:
            # Make room for the stop marker during shutdown.
            try:
                self._frame_queue.get_nowait()
                self._frame_queue.task_done()

            except queue.Empty:
                pass

            try:
                self._frame_queue.put_nowait(
                    _STOP_MARKER
                )

            except queue.Full:
                pass

        if self._thread is not None:
            self._thread.join(
                timeout=5
            )

        if (
            self._loop is not None
            and not self._loop.is_closed()
        ):
            self._loop.close()

        print(
            "RTMaps WebSocket sender stopped: "
            f"received={self._frames_received}, "
            f"encoded={self._frames_encoded}, "
            f"queued={self._frames_queued}, "
            f"sent={self._frames_sent}, "
            f"encoding_failures="
            f"{self._encoding_failures}"
        )