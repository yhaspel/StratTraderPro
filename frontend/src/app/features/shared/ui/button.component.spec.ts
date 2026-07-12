import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ButtonComponent } from './button.component';

describe('ButtonComponent', () => {
  let fixture: ComponentFixture<ButtonComponent>;
  let component: ButtonComponent;

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [ButtonComponent] }).compileComponents();
    fixture = TestBed.createComponent(ButtonComponent);
    component = fixture.componentInstance;
  });

  function btn(): HTMLButtonElement {
    return fixture.nativeElement.querySelector('button');
  }

  it('applies the primary variant by default', () => {
    fixture.detectChanges();
    expect(btn().className).toContain('bg-primary-600');
  });

  it('applies the danger variant', () => {
    component.variant = 'danger';
    fixture.detectChanges();
    expect(btn().className).toContain('bg-danger-500');
  });

  it('disables and marks aria-busy while loading', () => {
    component.loading = true;
    fixture.detectChanges();
    expect(btn().disabled).toBeTrue();
    expect(btn().getAttribute('aria-busy')).toBe('true');
  });

  it('emits clicked when pressed', () => {
    const spy = jasmine.createSpy('clicked');
    component.clicked.subscribe(spy);
    fixture.detectChanges();
    btn().click();
    expect(spy).toHaveBeenCalled();
  });
});
