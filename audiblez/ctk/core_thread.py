import threading
import audiblez.core as core

class CoreThread(threading.Thread):
    def __init__(self, params, callback):
        super().__init__()
        self.params = params
        self.callback = callback

    def run(self):
        try:
            core.main(**self.params, post_event=self.post_event)
        except Exception as e:
            self.post_event('error', error_message=str(e))

    def post_event(self, event_name, **kwargs):
        """Post an event to the UI using the provided callback."""
        if self.callback:
            self.callback(event_name, **kwargs)
