/** A demo entry must never override the deployed IAM authentication mode. */
export function shouldShowDemoPicker(privateIam: boolean, search: string, sessionMode?: string): boolean {
  return !privateIam && (new URLSearchParams(search).get('demo') === 'login' || sessionMode === 'google_iam');
}
