import { describe, expect, it } from 'vitest'
import { passwordExport } from './browser-import'

describe('Chrome password export import', () => {
  it('preserves CSV-quoted values and binds a login to the exact origin', () => {
    expect(passwordExport('\ufeffname,url,username,password\r\nExample,https://example.com:8443/login,"user,name","a,""quoted"" password"\r\n')).toEqual([
      { origin: 'https://example.com:8443', username: 'user,name', password: 'a,"quoted" password' }
    ])
  })
  it.each(['file:///secret', 'javascript:alert(1)', 'not a url'])('refuses non-website credential destinations: %s', url => {
    expect(() => passwordExport(`name,url,username,password\nExample,${url},user,password`)).toThrow()
  })
  it('rejects malformed or missing password data', () => {
    expect(() => passwordExport('name,url,username,password\nExample,https://example.com,user,')).toThrow()
    expect(() => passwordExport('name,url,username,password\nExample,"https://example.com,user,password')).toThrow()
  })
})
