using System;
using System.Collections.Generic;
using UnityEngine;

namespace BigBirdReturns.Axm.ActionPlayer
{
    public interface IActionInputSource
    {
        ActionInputFrame SampleActionInput();
    }

    public static class ActionInputQuantizer
    {
        public static int Axis(float value, float deadZone = 0.35f)
        {
            if (!float.IsFinite(value))
            {
                return 0;
            }

            float threshold = Mathf.Clamp(deadZone, 0.05f, 0.95f);
            if (value > threshold)
            {
                return 1;
            }

            if (value < -threshold)
            {
                return -1;
            }

            return 0;
        }

        public static int Buttons(bool light, bool heavy, bool dodge, bool parry)
        {
            int value = 0;
            if (light) value |= ActionBridgeProtocol.LightButton;
            if (heavy) value |= ActionBridgeProtocol.HeavyButton;
            if (dodge) value |= ActionBridgeProtocol.DodgeButton;
            if (parry) value |= ActionBridgeProtocol.ParryButton;
            return value & ActionBridgeProtocol.ButtonMask;
        }

        public static ActionInputFrame Normalize(ActionInputFrame input)
        {
            if (input == null)
            {
                return new ActionInputFrame();
            }

            return new ActionInputFrame
            {
                moveX = Math.Sign(input.moveX),
                moveY = Math.Sign(input.moveY),
                aimX = Math.Sign(input.aimX),
                aimY = Math.Sign(input.aimY),
                buttons = Math.Max(0, input.buttons) & ActionBridgeProtocol.ButtonMask
            };
        }
    }

    public sealed class ActionInputRunBuilder
    {
        private readonly int maximumTicks;
        private readonly List<ActionInputRun> runs = new List<ActionInputRun>();
        private int tickCount;

        public ActionInputRunBuilder(int maximumTicks)
        {
            this.maximumTicks = Mathf.Clamp(maximumTicks, 1, 120);
        }

        public int TickCount => tickCount;
        public bool IsFull => tickCount >= maximumTicks;
        public bool IsEmpty => tickCount == 0;

        public bool TryAppend(ActionInputFrame sample)
        {
            if (IsFull)
            {
                return false;
            }

            ActionInputFrame normalized = ActionInputQuantizer.Normalize(sample);
            if (runs.Count > 0)
            {
                ActionInputRun previous = runs[runs.Count - 1];
                if (previous.input.SameAs(normalized))
                {
                    previous.ticks += 1;
                    tickCount += 1;
                    return true;
                }
            }

            runs.Add(new ActionInputRun
            {
                ticks = 1,
                input = normalized
            });
            tickCount += 1;
            return true;
        }

        public ActionInputRun[] Drain()
        {
            ActionInputRun[] output = runs.ToArray();
            runs.Clear();
            tickCount = 0;
            return output;
        }

        public void Clear()
        {
            runs.Clear();
            tickCount = 0;
        }
    }

    public sealed class LegacyKeyboardActionInputSource : MonoBehaviour, IActionInputSource
    {
        [SerializeField, Range(0.05f, 0.95f)] private float analogDeadZone = 0.35f;
        [SerializeField] private bool useLegacyAxes;
        [SerializeField] private string horizontalAxis = "Horizontal";
        [SerializeField] private string verticalAxis = "Vertical";
        [SerializeField] private KeyCode lightKey = KeyCode.J;
        [SerializeField] private KeyCode heavyKey = KeyCode.K;
        [SerializeField] private KeyCode dodgeKey = KeyCode.Space;
        [SerializeField] private KeyCode parryKey = KeyCode.L;

        public ActionInputFrame SampleActionInput()
        {
            float horizontal = 0f;
            float vertical = 0f;

            if (useLegacyAxes)
            {
                horizontal = Input.GetAxisRaw(horizontalAxis);
                vertical = Input.GetAxisRaw(verticalAxis);
            }
            else
            {
                if (Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow)) horizontal -= 1f;
                if (Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow)) horizontal += 1f;
                if (Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow)) vertical -= 1f;
                if (Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow)) vertical += 1f;
            }

            int moveX = ActionInputQuantizer.Axis(horizontal, analogDeadZone);
            int moveY = ActionInputQuantizer.Axis(vertical, analogDeadZone);
            return new ActionInputFrame
            {
                moveX = moveX,
                moveY = moveY,
                aimX = moveX,
                aimY = moveY,
                buttons = ActionInputQuantizer.Buttons(
                    Input.GetKey(lightKey),
                    Input.GetKey(heavyKey),
                    Input.GetKey(dodgeKey),
                    Input.GetKey(parryKey))
            };
        }
    }
}
