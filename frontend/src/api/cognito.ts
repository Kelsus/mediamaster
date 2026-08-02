// Raw Cognito IDP calls — no SDK. USER_AUTH flow with PASSWORD and WEB_AUTHN
// challenges, plus passkey enrollment for a signed-in user.
import type { AppConfig } from './types'

let config: AppConfig | null = null

export async function getConfig(): Promise<AppConfig> {
  if (!config) {
    const resp = await fetch('/api/config')
    if (!resp.ok) throw new Error('Could not load app config')
    config = await resp.json()
  }
  return config!
}

async function cognito(target: string, body: object): Promise<any> {
  const cfg = await getConfig()
  const resp = await fetch(`https://cognito-idp.${cfg.region}.amazonaws.com/`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-amz-json-1.1',
      'X-Amz-Target': `AWSCognitoIdentityProviderService.${target}`,
    },
    body: JSON.stringify(body),
  })
  const data = await resp.json()
  if (!resp.ok) {
    const type = (data.__type || 'Error').split('#').pop()
    throw new Error(data.message || type)
  }
  return data
}

export interface Tokens {
  accessToken: string
  idToken: string
  refreshToken?: string
  expiresAt: number // epoch ms
}

function toTokens(result: any, existingRefresh?: string): Tokens {
  return {
    accessToken: result.AccessToken,
    idToken: result.IdToken,
    refreshToken: result.RefreshToken ?? existingRefresh,
    expiresAt: Date.now() + result.ExpiresIn * 1000,
  }
}

export async function passwordLogin(username: string, password: string): Promise<Tokens> {
  const cfg = await getConfig()
  let resp = await cognito('InitiateAuth', {
    AuthFlow: 'USER_AUTH',
    ClientId: cfg.client_id,
    AuthParameters: { USERNAME: username, PREFERRED_CHALLENGE: 'PASSWORD', PASSWORD: password },
  })
  // Depending on pool config Cognito may answer directly or ask us to pick /
  // answer the PASSWORD challenge explicitly.
  if (resp.ChallengeName === 'SELECT_CHALLENGE') {
    resp = await cognito('RespondToAuthChallenge', {
      ChallengeName: 'SELECT_CHALLENGE',
      ClientId: cfg.client_id,
      Session: resp.Session,
      ChallengeResponses: { USERNAME: username, ANSWER: 'PASSWORD', PASSWORD: password },
    })
  }
  if (resp.ChallengeName === 'PASSWORD') {
    resp = await cognito('RespondToAuthChallenge', {
      ChallengeName: 'PASSWORD',
      ClientId: cfg.client_id,
      Session: resp.Session,
      ChallengeResponses: { USERNAME: username, PASSWORD: password },
    })
  }
  if (!resp.AuthenticationResult) {
    throw new Error(`Unexpected challenge: ${resp.ChallengeName ?? 'none'}`)
  }
  return toTokens(resp.AuthenticationResult)
}

// --- WebAuthn helpers --------------------------------------------------------

const b64urlToBuf = (s: string): ArrayBuffer =>
  Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), (c) => c.charCodeAt(0)).buffer

const bufToB64url = (b: ArrayBuffer): string =>
  btoa(String.fromCharCode(...new Uint8Array(b)))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '')

function parseRequestOptions(json: any): CredentialRequestOptions {
  const pk = { ...json }
  pk.challenge = b64urlToBuf(pk.challenge)
  pk.allowCredentials = (pk.allowCredentials ?? []).map((c: any) => ({
    ...c,
    id: b64urlToBuf(c.id),
  }))
  return { publicKey: pk }
}

function parseCreationOptions(json: any): CredentialCreationOptions {
  const pk = { ...json }
  pk.challenge = b64urlToBuf(pk.challenge)
  pk.user = { ...pk.user, id: b64urlToBuf(pk.user.id) }
  pk.excludeCredentials = (pk.excludeCredentials ?? []).map((c: any) => ({
    ...c,
    id: b64urlToBuf(c.id),
  }))
  return { publicKey: pk }
}

function assertionToJSON(cred: PublicKeyCredential): object {
  if (typeof (cred as any).toJSON === 'function') return (cred as any).toJSON()
  const r = cred.response as AuthenticatorAssertionResponse
  return {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    authenticatorAttachment: (cred as any).authenticatorAttachment ?? undefined,
    clientExtensionResults: cred.getClientExtensionResults(),
    response: {
      authenticatorData: bufToB64url(r.authenticatorData),
      clientDataJSON: bufToB64url(r.clientDataJSON),
      signature: bufToB64url(r.signature),
      userHandle: r.userHandle ? bufToB64url(r.userHandle) : null,
    },
  }
}

function attestationToJSON(cred: PublicKeyCredential): object {
  if (typeof (cred as any).toJSON === 'function') return (cred as any).toJSON()
  const r = cred.response as AuthenticatorAttestationResponse
  return {
    id: cred.id,
    rawId: bufToB64url(cred.rawId),
    type: cred.type,
    authenticatorAttachment: (cred as any).authenticatorAttachment ?? undefined,
    clientExtensionResults: cred.getClientExtensionResults(),
    response: {
      attestationObject: bufToB64url(r.attestationObject),
      clientDataJSON: bufToB64url(r.clientDataJSON),
      transports: r.getTransports ? r.getTransports() : [],
    },
  }
}

export async function passkeyLogin(username: string): Promise<Tokens> {
  const cfg = await getConfig()
  const initiated = await cognito('InitiateAuth', {
    AuthFlow: 'USER_AUTH',
    ClientId: cfg.client_id,
    AuthParameters: { USERNAME: username, PREFERRED_CHALLENGE: 'WEB_AUTHN' },
  })
  if (initiated.ChallengeName !== 'WEB_AUTHN') {
    throw new Error(
      initiated.ChallengeName
        ? `No passkey available (got ${initiated.ChallengeName}); sign in with password and enroll one.`
        : 'No passkey challenge offered',
    )
  }
  const options = JSON.parse(initiated.ChallengeParameters.CREDENTIAL_REQUEST_OPTIONS)
  const cred = (await navigator.credentials.get(parseRequestOptions(options))) as PublicKeyCredential
  const resp = await cognito('RespondToAuthChallenge', {
    ChallengeName: 'WEB_AUTHN',
    ClientId: cfg.client_id,
    Session: initiated.Session,
    ChallengeResponses: { USERNAME: username, CREDENTIAL: JSON.stringify(assertionToJSON(cred)) },
  })
  if (!resp.AuthenticationResult) throw new Error('Passkey sign-in did not complete')
  return toTokens(resp.AuthenticationResult)
}

export async function refreshTokens(refreshToken: string): Promise<Tokens> {
  const cfg = await getConfig()
  const resp = await cognito('InitiateAuth', {
    AuthFlow: 'REFRESH_TOKEN_AUTH',
    ClientId: cfg.client_id,
    AuthParameters: { REFRESH_TOKEN: refreshToken },
  })
  return toTokens(resp.AuthenticationResult, refreshToken)
}

export async function listPasskeys(accessToken: string): Promise<any[]> {
  const resp = await cognito('ListWebAuthnCredentials', { AccessToken: accessToken, MaxResults: 20 })
  return resp.Credentials ?? []
}

export async function enrollPasskey(accessToken: string): Promise<void> {
  const start = await cognito('StartWebAuthnRegistration', { AccessToken: accessToken })
  const cred = (await navigator.credentials.create(
    parseCreationOptions(start.CredentialCreationOptions),
  )) as PublicKeyCredential
  await cognito('CompleteWebAuthnRegistration', {
    AccessToken: accessToken,
    Credential: attestationToJSON(cred),
  })
}
