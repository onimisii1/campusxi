import { useEffect } from 'react'
import PageHeader from '../components/PageHeader'
import SignIn from '../components/SignIn'
import { go, returnAfterSignIn } from '../router'
import { useSession } from '../session'

export default function SignInPage() {
  const { status, reload } = useSession()

  useEffect(() => {
    if (status === 'ready') returnAfterSignIn()
    if (status === 'needs_profile') go('/profile')
  }, [status])

  return <section><PageHeader title="Sign in" back="#/" /><SignIn onSignedIn={reload} /></section>
}
