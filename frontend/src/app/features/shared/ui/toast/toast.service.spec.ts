import { fakeAsync, TestBed, tick } from '@angular/core/testing';
import { ToastService } from './toast.service';

describe('ToastService', () => {
  let svc: ToastService;

  beforeEach(() => {
    TestBed.configureTestingModule({});
    svc = TestBed.inject(ToastService);
  });

  it('queues toasts and dismisses by id', () => {
    svc.success('ok');
    svc.error('bad');
    expect(svc.toasts().length).toBe(2);
    const first = svc.toasts()[0].id;
    svc.dismiss(first);
    expect(svc.toasts().length).toBe(1);
    expect(svc.toasts()[0].message).toBe('bad');
  });

  it('tags error toasts with the error kind', () => {
    svc.error('boom');
    expect(svc.toasts().some((t) => t.kind === 'error')).toBeTrue();
  });

  it('auto-dismisses after the timeout', fakeAsync(() => {
    svc.info('later');
    expect(svc.toasts().length).toBe(1);
    tick(6000);
    expect(svc.toasts().length).toBe(0);
  }));
});
