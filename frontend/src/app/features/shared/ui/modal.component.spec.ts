import { Component, ViewChild } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ModalComponent } from './modal.component';

@Component({
  standalone: true,
  imports: [ModalComponent],
  template: `
    <button id="opener">opener</button>
    <app-modal [open]="open" heading="Title" (closed)="open = false">
      <button id="a">A</button>
      <button id="b">B</button>
    </app-modal>
  `,
})
class HostComponent {
  open = false;
  @ViewChild(ModalComponent) modal!: ModalComponent;
}

describe('ModalComponent', () => {
  let fixture: ComponentFixture<HostComponent>;
  let host: HostComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [HostComponent] }).compileComponents();
    fixture = TestBed.createComponent(HostComponent);
    host = fixture.componentInstance;
    document.body.appendChild(fixture.nativeElement);
    fixture.detectChanges();
  });

  afterEach(() => {
    fixture.nativeElement.remove();
  });

  function open(): void {
    host.open = true;
    fixture.detectChanges();
  }

  it('renders a labelled dialog when open', () => {
    open();
    const dialog = fixture.nativeElement.querySelector('[role="dialog"]');
    expect(dialog).toBeTruthy();
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(dialog.getAttribute('aria-labelledby')).toBeTruthy();
  });

  it('closes on Escape', () => {
    open();
    const dialog = fixture.nativeElement.querySelector('[role="dialog"]');
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();
    expect(host.open).toBeFalse();
  });

  it('traps Tab within the dialog (wraps, stays inside)', () => {
    (document.getElementById('opener') as HTMLElement).focus();
    open();
    const b = document.getElementById('b') as HTMLElement;
    b.focus(); // last focusable
    const dialog = fixture.nativeElement.querySelector('[role="dialog"]');
    dialog.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }));
    // Focus wraps to the first focusable (the close button) — never escapes.
    expect(dialog.contains(document.activeElement)).toBeTrue();
    expect(document.activeElement?.id).not.toBe('opener');
  });

  it('restores focus to the opener on close', () => {
    const opener = document.getElementById('opener') as HTMLElement;
    opener.focus();
    open();
    host.open = false;
    fixture.detectChanges();
    expect(document.activeElement?.id).toBe('opener');
  });
});
