from __future__ import annotations

import asyncio
import base64

import cv2
import websockets

VIDEO_PATH = "output.mp4"

HOST = "localhost"
PORT = 8765

#JPEG_QUALITY = 80
JPEG_QUALITY = 40


async def stream_video(websocket):

    cap = cv2.VideoCapture(VIDEO_PATH)

    sent_frames = 0

    fps = cap.get(cv2.CAP_PROP_FPS)

    if fps <= 0:
        #fps = 25.0
        fps = 10.0

    delay = 1.0 / fps

    total_frames = int(
        cap.get(cv2.CAP_PROP_FRAME_COUNT)
    )

    print(
        f"VIDEO INFO : "
        f"fps={fps}, "
        f"frames={total_frames}, "
        f"delay={delay:.4f}s"
    )

    try:

        while True:

            success, frame = cap.read()

            if not success:
                print(
                    f"SENDER transmitted "
                    f"{sent_frames} frames"
                )
                break

            #
            # Visualisation locale du flux webcam
            #
            preview = frame.copy()

            cv2.putText(
                preview,
                f"Frame {sent_frames + 1}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 0),
                2,
            )

            cv2.imshow(
                "Webcam Stream Sent To WebSocket",
                preview,
            )

            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), 27):
                print(
                    "Webcam preview stopped by user"
                )
                break
            
            ok, buffer = cv2.imencode(
                ".jpg",
                frame,
                [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY],
            )

            if not ok:
                print(
                    f"JPEG encoding failed "
                    f"at frame {sent_frames + 1}"
                )
                continue

            message = base64.b64encode(
                buffer
            ).decode("utf-8")

            sent_frames += 1

            try:

                await websocket.send(
                    message
                )

            except Exception as exc:

                print(
                    f"SEND ERROR at frame "
                    f"{sent_frames}: {exc}"
                )

                raise

            if sent_frames % 100 == 0:

                print(
                    f"SENDER transmitted "
                    f"{sent_frames} frames"
                )

            await asyncio.sleep(delay)

    finally:

        print(
            f"SENDER FINAL COUNT = "
            f"{sent_frames}"
        )

        cap.release()
        cv2.destroyAllWindows()


async def main():

    async with websockets.serve(
        stream_video,
        HOST,
        PORT,
        ping_interval=None,
    ):

        print(
            f"Video websocket server running on "
            f"ws://{HOST}:{PORT}"
        )

        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())