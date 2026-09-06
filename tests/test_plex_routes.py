import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app


class PlexRouteTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        for target,value in [('app.main.CONFIG_DIR',Path(directory.name)),('app.main.settings',{})]:
            mock=patch(target,return_value=value) if target.endswith('settings') else patch(target,value)
            mock.start(); self.addCleanup(mock.stop)
        self.client=TestClient(app)
        self.payload={'source':'tidal','playlist_name':'Mix','playlist_url':'','tracks':[{'artist':'Artist','title':'Song'}]}

    def test_status_is_safe_and_missing_configuration_is_actionable(self):
        status=self.client.get('/api/status').json()
        self.assertEqual({'configured':False,'library_name':'Music'},status['plex'])
        response=self.client.post('/api/plex/match',json=self.payload)
        self.assertEqual(400,response.status_code)
        self.assertIn('PLEX_URL',response.json()['detail'])
        self.assertEqual([],self.client.get('/api/plex/drafts').json())

    def test_malformed_source_tracks_and_unsafe_choice_are_rejected(self):
        response=self.client.post('/api/plex/match',json={**self.payload,'tracks':[{'title':'Missing artist'}]})
        self.assertEqual(422,response.status_code)
        self.assertEqual(422,self.client.patch('/api/plex/matches/abc',json={'index':-1,'rating_key':'1'}).status_code)

    @patch('app.plex.PlexServer')
    @patch('app.main.settings')
    def test_provider_exception_never_returns_token(self,settings,server):
        import requests
        settings.return_value={'PLEX_URL':'http://plex:32400','PLEX_TOKEN':'secret-abc','PLEX_MUSIC_LIBRARY':'Music'}
        server.side_effect=requests.HTTPError('upstream secret-abc')
        response=self.client.post('/api/plex/match',json=self.payload)
        self.assertEqual(502,response.status_code)
        self.assertNotIn('secret-abc',response.text)
        self.assertIn('Plex',response.json()['detail'])
