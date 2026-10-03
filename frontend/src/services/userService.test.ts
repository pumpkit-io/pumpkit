import { afterEach, describe, expect, it, vi } from 'vitest';
import { apiService } from './apiService';
import { userService } from './userService';

const response = { email: 'a@example.com', first_name: 'Ada', last_name: null, avatar_data_url: null };

describe('userService.updateProfile', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends only the keys the caller set (omitted is not null)', async () => {
    const patch = vi.spyOn(apiService, 'patch').mockResolvedValue({ data: response } as never);
    const profile = await userService.updateProfile({ firstName: 'Ada' });
    expect(patch).toHaveBeenCalledWith('/users/me', { first_name: 'Ada' });
    expect(profile).toEqual({ email: 'a@example.com', firstName: 'Ada', lastName: null, avatarUrl: null });
  });

  it('sends explicit nulls to clear fields', async () => {
    const patch = vi.spyOn(apiService, 'patch').mockResolvedValue({ data: response } as never);
    await userService.updateProfile({ avatarUrl: null });
    expect(patch).toHaveBeenCalledWith('/users/me', { avatar_data_url: null });
  });
});
