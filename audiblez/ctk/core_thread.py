import threading
import audiblez.core as core

class CoreThread(threading.Thread):
    def __init__(self, params, callback, pause_event=None, stop_event=None):
        super().__init__()
        self.params = params
        self.callback = callback
        self.pause_event = pause_event
        self.stop_event = stop_event

    def run(self):
        try:
            # Pass events to core.main
            self.params['pause_event'] = self.pause_event
            self.params['stop_event'] = self.stop_event
            core.main(**self.params, post_event=self.post_event)
        except Exception as e:
            self.post_event('error', error_message=str(e))

    def post_event(self, event_name, **kwargs):
        """Post an event to the UI using the provided callback."""
        if self.callback:
            self.callback(event_name, **kwargs)
