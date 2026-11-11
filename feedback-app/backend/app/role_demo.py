"""IAP-bound Demo Admin capability; previews are restricted to the demo tenant."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from urllib.parse import urlsplit

from fastapi import HTTPException,Request

from .config import settings
from .demo_context import is_demo

COOKIE='neo_role_demo'
ROLE='demo_admin'
PERSONAS=(
    {'email':'alex.requester@example.test','displayName':'Alex Reporter','role':'reporter'},
    {'email':'sam.requester@example.test','displayName':'Sam Reporter','role':'reporter'},
    {'email':'quality.reviewer@example.test','displayName':'Demo Reviewer','role':'reviewer'},
)
AUDIENCE='feedback-role-demo-v1'


def require_enabled():
    if not settings.role_demo_enabled or settings.auth_mode!='google_iam':raise HTTPException(404,'Demo views are not enabled')
    origin=urlsplit(settings.demo_frontend_origin)
    local=not os.getenv('K_SERVICE')and origin.scheme=='http'and origin.hostname in{'localhost','127.0.0.1','::1'}
    if (settings.dataset=='agent_quality_demo' or os.getenv('K_SERVICE')not in{None,'neo-feedback-api'}
            or os.getenv('K_SERVICE') and not settings.auth_secret
            or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment
            or origin.path not in{'','/'}or settings.demo_frontend_origin.endswith('/')or(origin.scheme!='https'and not local)):
        raise HTTPException(503,'In-app demo isolation is not configured correctly')


def require_demo_scope():
    require_enabled()
    if not is_demo():raise HTTPException(403,'A verified demo-view context is required')


def require_action(request,*,enabled=True):
    if enabled:require_enabled()
    elif settings.auth_mode!='google_iam':raise HTTPException(404,'Demo views are not enabled')
    if(request.headers.get('origin')!=settings.demo_frontend_origin or request.headers.get('x-feedback-csrf')!='1'
            or request.headers.get('x-requested-with')!='XMLHttpRequest'or request.headers.get('sec-fetch-site')=='cross-site'):
        raise HTTPException(403,'A same-origin demo action is required')


def authorize_actor(user,*,fresh=True):
    if user.access_role!=ROLE or user.presenter_email:raise HTTPException(403,'Demo Admin application role required')
    if fresh:
        from .access_repository import access_repository
        grant=access_repository().grant(user.email,refresh=True)
        if not grant or grant['role']!=ROLE:raise HTTPException(403,'Your Demo Admin role changed; refresh the app')
    return user


def controller(request):
    require_enabled()
    return authorize_actor(getattr(request.state,'real_user',None)or request.state.user)


def persona(email):return next((dict(value)for value in PERSONAS if value['email']==email),None)


def _key():
    from .auth import _TOKEN_SECRET
    return _TOKEN_SECRET


def _actor(user):return hmac.new(_key(),('role-demo-actor:'+user.email).encode(),hashlib.sha256).hexdigest()


def issue_view(user,email):
    require_enabled()
    if user.access_role!=ROLE or user.presenter_email:raise HTTPException(403,'Demo Admin application role required')
    if not persona(email):raise HTTPException(422,'Choose a configured demo Reporter or Reviewer')
    payload={'aud':AUDIENCE,'actor':_actor(user),'persona':email,'exp':int(time.time())+1800,'nonce':secrets.token_hex(12)}
    encoded=base64.urlsafe_b64encode(json.dumps(payload,separators=(',',':')).encode()).decode().rstrip('=')
    mac=base64.urlsafe_b64encode(hmac.new(_key(),(AUDIENCE+':'+encoded).encode(),hashlib.sha256).digest()).decode().rstrip('=')
    return encoded+'.'+mac


def decode_view(user,token,*,fresh=True):
    require_enabled()
    authorize_actor(user,fresh=fresh)
    try:
        if not isinstance(token,str)or len(token)>2048:raise ValueError()
        encoded,signature=token.split('.')
        expected=base64.urlsafe_b64encode(hmac.new(_key(),(AUDIENCE+':'+encoded).encode(),hashlib.sha256).digest()).decode().rstrip('=')
        if not hmac.compare_digest(signature,expected):raise ValueError()
        data=json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
        if not isinstance(data,dict) or set(data)!={'aud','actor','persona','exp','nonce'}:raise ValueError()
        selected=persona(data.get('persona'))
        if(data.get('aud')!=AUDIENCE or not hmac.compare_digest(str(data.get('actor','')),_actor(user))
                or type(data.get('exp')) is not int or not time.time()<data['exp']<=time.time()+1830
                or not selected or not re.fullmatch(r'[a-f0-9]{24}',str(data.get('nonce','')))):
            raise ValueError()
    except(ValueError,TypeError,KeyError,UnicodeDecodeError,binascii.Error):
        raise HTTPException(401,'Invalid or expired demo view; exit demo and choose again')from None
    from .auth import AuthenticatedUser
    return AuthenticatedUser(selected['email'],selected['displayName'],selected['role'],
        presenter_email=user.email,demo_session_scope=data['nonce'],access_role=ROLE)


def status(user,selected=None):
    return {'enabled':True,'active':selected is not None,'admin':{'username':user.display_name,'displayName':user.display_name},
        'personas':[dict(value)for value in PERSONAS],'user':selected.public_dict()if selected else None,
        'realUser':user.public_dict(),'simulatedAi':True}
